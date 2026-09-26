from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest
import requests

from geektime_dl.core.api import (
    ALL_COURSE_URL,
    ARTICLE_DETAIL_URL,
    ApiCache,
    AuthenticationError,
    GeektimeApi,
    GeektimeApiError,
)


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]):
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


class QueueSession:
    def __init__(self, responses: list[FakeResponse | Exception]):
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.headers: dict[str, Any] = {}

    def post(self, url: str, json: dict[str, Any], timeout: int) -> FakeResponse:
        self.requests.append((url, json))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def success(data: Any) -> FakeResponse:
    return FakeResponse(200, {"code": 0, "data": data, "error": {}})


def standard_course(course_id: int, title: str) -> dict[str, Any]:
    return {
        "id": course_id,
        "type": "c1",
        "title": title,
        "subtitle": "副标题",
        "author": {"name": "作者", "intro": "介绍"},
        "column": {"unit": "讲", "update_frequency": "已完结"},
        "cover": {"lecture_horizontal": "https://example.com/cover.png"},
        "intro_html": "<p>课程介绍</p>",
        "is_audio": True,
        "is_video": False,
    }


def test_all_course_list_fetches_all_pages_and_normalizes(tmp_path: Path) -> None:
    session = QueueSession(
        [
            success({"products": [standard_course(1, "第一门")], "page": {"more": True}}),
            success({"products": [standard_course(2, "第二门")], "page": {"more": False}}),
        ]
    )
    cache = ApiCache(tmp_path)
    result = GeektimeApi(session=session, cache=cache, credentials={}).list_courses(
        "all", ["c1"]
    )

    assert [course["id"] for course in result.data] == ["1", "2"]
    assert result.categories == {"c1": {"name": "专栏", "count": 2}}
    assert [request[1]["prev"] for request in session.requests] == [1, 2]
    assert all(request[0] == ALL_COURSE_URL for request in session.requests)
    cache_files = list(tmp_path.glob("product-list-*.json"))
    assert len(cache_files) == 2
    assert stat.S_IMODE(cache_files[0].stat().st_mode) == 0o600


def test_purchased_list_supports_nested_product_and_filters_types(tmp_path: Path) -> None:
    purchased = {
        "product": {
            "id": 10,
            "type": "c3",
            "title": "视频课",
            "author": {"name": "讲师"},
            "is_video": True,
        }
    }
    session = QueueSession([success({"list": [purchased], "page": {"more": False}})])
    result = GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={}).list_courses(
        "purchased", ["c3"]
    )

    assert result.data[0]["id"] == "10"
    assert result.data[0]["type_name"] == "视频课"
    assert result.data[0]["purchased"] is True


def test_unfiltered_purchased_list_keeps_unknown_upstream_types(tmp_path: Path) -> None:
    unknown = {"id": 11, "type": "new-type", "title": "新分类课程"}
    session = QueueSession([success({"list": [unknown], "page": {"more": False}})])
    result = GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={}).list_courses()

    assert result.data[0]["type"] == "new-type"
    assert result.data[0]["type_name"] == "unknown"
    assert result.categories["new-type"] == {"name": "unknown", "count": 1}


def test_daily_course_info_and_chapters_are_standalone(tmp_path: Path) -> None:
    daily = {
        "id": 7,
        "type": "d",
        "title": "每日课程",
        "article": {"id": 99},
        "author": {"name": "作者"},
        "cover": {"square": "https://example.com/d.png"},
    }
    detail = {
        "info": {
            "id": 99,
            "title": "每日课程",
            "content": "<p>详细介绍</p>",
            "author": {"name": "作者"},
            "cover": {"default": "https://example.com/d.png"},
        }
    }
    session = QueueSession(
        [
            success({"list": [daily], "page": {"more": False}}),
            success(detail),
        ]
    )
    api = GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={})
    info = api.get_course_info("7", "d")

    assert info.data["article_id"] == "99"
    assert "详细介绍" in info.data["intro_markdown"]

    session.responses.extend(
        [
            success({"list": [daily], "page": {"more": False}}),
            success(detail),
        ]
    )
    chapters = api.list_chapters("7", "d")
    assert chapters.data == {
        "course_id": "7",
        "course_type": "d",
        "standalone": True,
        "article_id": "99",
        "chapters": [],
    }


def test_chapters_without_type_resolve_daily_course_before_querying_chapters(
    tmp_path: Path,
) -> None:
    daily = {"id": 7, "type": "d", "title": "每日课程", "article": {"id": 99}}
    detail = {
        "info": {
            "id": 99,
            "title": "每日课程",
            "content": "<p>介绍</p>",
            "author": {},
            "cover": {},
        }
    }
    empty_standard = success({"products": [], "page": {"more": False}})
    session = QueueSession(
        [
            empty_standard,
            success({"products": [], "page": {"more": False}}),
            success({"products": [], "page": {"more": False}}),
            success({"list": [daily], "page": {"more": False}}),
            success(detail),
        ]
    )
    result = GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={}).list_chapters(
        "7"
    )

    assert result.data["standalone"] is True
    assert result.data["article_id"] == "99"
    assert all(url != "https://time.geekbang.org/serv/v1/chapters" for url, _ in session.requests)


def test_article_detail_normalizes_content_neighbors_and_media(tmp_path: Path) -> None:
    article = {
        "id": 88,
        "cid": 10,
        "chapter_id": 20,
        "product_type": "c3",
        "article_title": "文章",
        "article_content": "<h2>正文</h2>",
        "author_name": "作者",
        "neighbors": {
            "left": {"id": 87, "article_title": "上一篇"},
            "right": {},
        },
        "audio_download_url": "https://example.com/audio.mp3",
        "hls_videos": {"sd": {"url": "https://example.com/video.m3u8", "size": 3}},
        "subtitles": [{"language": "zh", "url": "https://example.com/sub.vtt"}],
    }
    session = QueueSession([success(article)])
    result = GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={}).get_article_detail(
        "88"
    )

    assert session.requests[0][0] == ARTICLE_DETAIL_URL
    assert result.data["id"] == "88"
    assert "正文" in result.data["content_markdown"]
    assert result.data["neighbors"]["left"]["id"] == "87"
    assert result.data["media"]["video"][0]["quality"] == "sd"


def test_network_failure_uses_stale_cache_but_auth_failure_does_not(tmp_path: Path) -> None:
    payload = {"products": [standard_course(1, "课程")], "page": {"more": False}}
    cache = ApiCache(tmp_path)
    first = GeektimeApi(
        session=QueueSession([success(payload)]), cache=cache, credentials={}
    ).list_courses("all", ["c1"])
    assert first.stale is False

    stale = GeektimeApi(
        session=QueueSession([requests.ConnectionError("offline")]),
        cache=cache,
        credentials={},
    ).list_courses("all", ["c1"])
    assert stale.stale is True
    assert stale.cached is True
    assert stale.data[0]["id"] == "1"

    auth_response = FakeResponse(
        400, {"code": -1, "data": {}, "error": {"code": -2000, "msg": "登录错误"}}
    )
    with pytest.raises(AuthenticationError):
        GeektimeApi(
            session=QueueSession([auth_response]), cache=cache, credentials={}
        ).list_courses("all", ["c1"])


def test_server_error_uses_stale_cache(tmp_path: Path) -> None:
    payload = {"products": [standard_course(1, "课程")], "page": {"more": False}}
    cache = ApiCache(tmp_path)
    GeektimeApi(
        session=QueueSession([success(payload)]), cache=cache, credentials={}
    ).list_courses("all", ["c1"])

    result = GeektimeApi(
        session=QueueSession([FakeResponse(503, {})]), cache=cache, credentials={}
    ).list_courses("all", ["c1"])
    assert result.stale is True


def test_malformed_success_response_is_not_reported_as_empty(tmp_path: Path) -> None:
    with pytest.raises(GeektimeApiError, match="list 或 products"):
        GeektimeApi(
            session=QueueSession([success({})]), cache=ApiCache(tmp_path), credentials={}
        ).list_courses("purchased")


def test_corrupt_cache_is_not_used(tmp_path: Path) -> None:
    api = GeektimeApi(
        session=QueueSession([requests.ConnectionError("offline")]),
        cache=ApiCache(tmp_path),
        credentials={},
    )
    payload = {
        "tag_ids": [],
        "product_type": 1,
        "product_form": 1,
        "pvip": 0,
        "prev": 1,
        "size": 300,
        "sort": 1,
        "with_articles": True,
    }
    path = api.cache.response_path(ALL_COURSE_URL, payload)
    tmp_path.mkdir(exist_ok=True)
    path.write_text("not json", encoding="utf-8")

    with pytest.raises(GeektimeApiError, match="网络请求失败"):
        api.list_courses("all", ["c1"])


def test_cache_wrapper_contains_only_response_and_request_metadata(tmp_path: Path) -> None:
    session = QueueSession(
        [success({"products": [standard_course(1, "课程")], "page": {"more": False}})]
    )
    GeektimeApi(session=session, cache=ApiCache(tmp_path), credentials={}).list_courses(
        "all", ["c1"]
    )
    cached = json.loads(next(tmp_path.glob("product-list-*.json")).read_text(encoding="utf-8"))
    assert set(cached) == {"fetched_at", "url", "request", "response"}
    assert "Cookie" not in json.dumps(cached)
