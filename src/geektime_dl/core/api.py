"""Read-only Geektime API client used by query-oriented CLI commands."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import html2text
import requests
from platformdirs import user_cache_dir

from geektime_dl.utils.config import load_credentials

ALL_COURSE_URL = "https://time.geekbang.org/serv/v4/pvip/product_list"
PURCHASED_COURSE_URL = "https://time.geekbang.org/serv/v3/learn/product"
CHAPTER_URL = "https://time.geekbang.org/serv/v1/chapters"
ARTICLE_LIST_URL = "https://time.geekbang.org/serv/v1/column/articles"
ARTICLE_DETAIL_URL = "https://time.geekbang.org/serv/v1/article"
V3_LIST_URL = "https://time.geekbang.org/serv/v3/product/list"
V3_DETAIL_URL = "https://time.geekbang.org/serv/v3/article/info"

COURSE_TYPE_NAMES = {
    "c1": "专栏",
    "c3": "视频课",
    "p": "公开课",
    "d": "每日一课",
    "q": "大厂案例课",
}

STANDARD_COURSE_TYPES = {
    "c1": {"product_type": 1, "product_form": 1},
    "c3": {"product_type": 1, "product_form": 2},
    "p": {"product_type": 4, "product_form": 1},
}

DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    "Content-Type": "application/json",
    "Origin": "https://time.geekbang.org",
    "Referer": "https://time.geekbang.org/",
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
    ),
}


class GeektimeApiError(RuntimeError):
    """Base error for read-only Geektime API operations."""


class AuthenticationError(GeektimeApiError):
    """The saved credentials are missing, expired, or unauthorized."""


class ResourceNotFoundError(GeektimeApiError):
    """The requested course or article does not exist."""


class _TransientApiError(GeektimeApiError):
    """A network or server failure that may use stale cache."""


@dataclass
class FetchResult:
    response: dict[str, Any]
    source: str
    fetched_at: str
    cached: bool = False
    stale: bool = False


@dataclass
class QueryResult:
    data: Any
    raw: Any
    sources: list[str]
    fetched_at: str
    cached: bool = False
    stale: bool = False
    categories: dict[str, Any] | None = None

    def payload(self) -> dict[str, Any]:
        result = {
            "data": self.data,
            "source": self.sources,
            "fetched_at": self.fetched_at,
            "cached": self.cached,
            "stale": self.stale,
        }
        if self.categories is not None:
            result["categories"] = self.categories
        return result


class ApiCache:
    """Private, atomic cache for raw successful API responses and ID indexes."""

    def __init__(self, root: Path | None = None):
        self.root = root or Path(user_cache_dir("geektime")) / "api"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            self.root.chmod(0o700)

    def response_path(self, url: str, payload: dict[str, Any]) -> Path:
        request_key = json.dumps(
            {"url": url, "payload": payload}, sort_keys=True, ensure_ascii=False
        ).encode("utf-8")
        digest = hashlib.sha256(request_key).hexdigest()
        endpoint = url.rstrip("/").rsplit("/", 1)[-1].replace("_", "-")
        return self.root / f"{endpoint}-{digest}.json"

    def load(self, url: str, payload: dict[str, Any]) -> dict[str, Any] | None:
        path = self.response_path(url, payload)
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return None
        if not isinstance(cached, dict) or not isinstance(cached.get("response"), dict):
            return None
        return cached

    def save(self, url: str, payload: dict[str, Any], response: dict[str, Any]) -> str:
        fetched_at = _utc_now()
        wrapper = {
            "fetched_at": fetched_at,
            "url": url,
            "request": payload,
            "response": response,
        }
        self._atomic_write(self.response_path(url, payload), wrapper)
        return fetched_at

    def load_index(self) -> dict[str, Any]:
        try:
            index = json.loads((self.root / "course-index.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return {"courses": {}, "articles": {}}
        if not isinstance(index, dict):
            return {"courses": {}, "articles": {}}
        index.setdefault("courses", {})
        index.setdefault("articles", {})
        return index

    def update_index(self, courses: Iterable[dict[str, Any]]) -> None:
        index = self.load_index()
        for course in courses:
            course_id = str(course.get("id") or "")
            course_type = str(course.get("type") or "unknown")
            if not course_id:
                continue
            item = {"type": course_type}
            article_id = str(course.get("article_id") or "")
            if article_id:
                item["article_id"] = article_id
                index["articles"][article_id] = {"type": course_type, "course_id": course_id}
            index["courses"][course_id] = item
        self._atomic_write(self.root / "course-index.json", index)

    def _atomic_write(self, path: Path, value: dict[str, Any]) -> None:
        self._ensure_root()
        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as temp_file:
                json.dump(value, temp_file, indent=2, ensure_ascii=False)
                temp_file.write("\n")
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.chmod(temp_name, 0o600)
            os.replace(temp_name, path)
            path.chmod(0o600)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)


class GeektimeApi:
    """Read-only API facade with normalized results and safe stale fallback."""

    def __init__(
        self,
        session: requests.Session | Any | None = None,
        cache: ApiCache | None = None,
        timeout: int = 30,
        credentials: dict[str, Any] | None = None,
    ):
        self.session = session or requests.Session()
        self.cache = cache or ApiCache()
        self.timeout = timeout
        headers = dict(DEFAULT_HEADERS)
        headers.update(credentials if credentials is not None else (load_credentials() or {}))
        if hasattr(self.session, "headers"):
            self.session.headers.update(headers)

    def list_courses(
        self, scope: str = "purchased", course_types: list[str] | None = None
    ) -> QueryResult:
        has_type_filter = course_types is not None
        selected_types = course_types or list(COURSE_TYPE_NAMES)
        _validate_course_types(selected_types)
        if scope not in {"all", "purchased"}:
            raise ValueError(f"未知课程范围: {scope}")

        if scope == "purchased":
            entries, pages = self._fetch_purchased_courses()
            if has_type_filter:
                entries = [
                    entry for entry in entries if _infer_course_type(entry) in selected_types
                ]
        else:
            entries = []
            pages = []
            for course_type in selected_types:
                type_entries, type_pages = self._fetch_catalog_type(course_type)
                entries.extend(type_entries)
                pages.extend(type_pages)

        courses = _deduplicate_courses(
            [_normalize_course(item, purchased=scope == "purchased") for item in entries]
        )
        self.cache.update_index(courses)
        categories = _category_counts(courses, selected_types)
        return _combine_results(
            data=courses,
            raw={
                "scope": scope,
                "pages": [
                    {"type": page_type, "response": result.response}
                    for page_type, result in pages
                ],
            },
            fetches=[result for _, result in pages],
            categories=categories,
        )

    def get_course_info(
        self, course_id: str | int, course_type: str | None = None
    ) -> QueryResult:
        target_id = str(course_id)
        candidate_types = self._candidate_course_types(target_id, course_type)
        all_fetches: list[FetchResult] = []

        for candidate in candidate_types:
            entries, pages = self._fetch_catalog_type(candidate)
            all_fetches.extend(result for _, result in pages)
            match = next((item for item in entries if _course_id(item) == target_id), None)
            if match is None:
                continue

            normalized = _normalize_course_info(match, candidate)
            raw: dict[str, Any] = {
                "catalog": _raw_page_for_course(pages, target_id) or match
            }
            if candidate in {"d", "q"}:
                article_id = normalized.get("article_id")
                if article_id:
                    detail_fetch = self._fetch(V3_DETAIL_URL, {"id": article_id})
                    all_fetches.append(detail_fetch)
                    detail = _extract_v3_detail(detail_fetch.response)
                    if not detail:
                        raise ResourceNotFoundError(f"未找到课程介绍: {target_id}")
                    normalized = _merge_dq_course_detail(normalized, detail)
                    raw["detail"] = detail_fetch.response
            self.cache.update_index([normalized])
            return _combine_results(normalized, raw, all_fetches)

        # A purchased product may no longer be present in the public catalogue.
        purchased_entries, purchased_pages = self._fetch_purchased_courses()
        all_fetches.extend(result for _, result in purchased_pages)
        match = next((item for item in purchased_entries if _course_id(item) == target_id), None)
        if match is not None:
            normalized = _normalize_course_info(match, _infer_course_type(match), purchased=True)
            self.cache.update_index([normalized])
            return _combine_results(
                normalized,
                {"purchased": _raw_page_for_course(purchased_pages, target_id) or match},
                all_fetches,
            )
        raise ResourceNotFoundError(f"未找到课程: {target_id}")

    def list_chapters(
        self, course_id: str | int, course_type: str | None = None
    ) -> QueryResult:
        target_id = str(course_id)
        resolved_type = course_type or self._indexed_course_type(target_id)
        resolved_info: QueryResult | None = None
        if resolved_type is None:
            resolved_info = self.get_course_info(target_id)
            resolved_type = str(resolved_info.data.get("type") or "unknown")
        if resolved_type in {"d", "q"}:
            info = resolved_info or self.get_course_info(target_id, resolved_type)
            article_id = str(info.data.get("article_id") or "")
            data = {
                "course_id": target_id,
                "course_type": resolved_type,
                "standalone": True,
                "article_id": article_id,
                "chapters": [],
            }
            return QueryResult(
                data=data,
                raw=info.raw,
                sources=info.sources,
                fetched_at=info.fetched_at,
                cached=info.cached,
                stale=info.stale,
            )

        fetch = self._fetch(CHAPTER_URL, {"cid": course_id})
        chapters_raw = fetch.response.get("data")
        if not isinstance(chapters_raw, list):
            raise GeektimeApiError("章节接口未返回列表")
        chapters = [
            {
                "id": str(chapter.get("id") or ""),
                "title": str(chapter.get("title") or ""),
                "article_count": int(chapter.get("article_count") or 0),
                "order": index,
                "article_id": "",
            }
            for index, chapter in enumerate(chapters_raw)
            if isinstance(chapter, dict)
        ]
        result = _combine_results(
            {"course_id": target_id, "course_type": resolved_type, "standalone": False, "chapters": chapters},
            fetch.response,
            [fetch],
        )
        if resolved_info is not None:
            result.raw = {"course": resolved_info.raw, "chapters": fetch.response}
            result.sources = list(dict.fromkeys([*resolved_info.sources, *result.sources]))
            result.fetched_at = max(resolved_info.fetched_at, result.fetched_at)
            result.cached = resolved_info.cached and result.cached
            result.stale = resolved_info.stale or result.stale
        return result

    def get_article_detail(self, article_id: str | int) -> QueryResult:
        target_id = str(article_id)
        article_type = self._indexed_article_type(target_id)
        if article_type in {"d", "q"}:
            return self._get_v3_article_detail(target_id, article_type)

        first_error: GeektimeApiError | None = None
        try:
            fetch = self._fetch(
                ARTICLE_DETAIL_URL,
                {"id": article_id, "include_neighbors": True, "is_freelyread": True},
            )
            detail = fetch.response.get("data")
            if isinstance(detail, dict) and detail:
                return _combine_results(
                    _normalize_article(detail), fetch.response, [fetch]
                )
        except AuthenticationError:
            raise
        except GeektimeApiError as exc:
            first_error = exc

        try:
            return self._get_v3_article_detail(target_id, article_type or "unknown")
        except AuthenticationError:
            raise
        except GeektimeApiError as exc:
            if first_error is not None:
                raise first_error from exc
            raise ResourceNotFoundError(f"未找到文章: {target_id}") from exc

    def list_articles(
        self, course_id: str | int, chapter_ids: list[str] | None = None
    ) -> QueryResult:
        payload: dict[str, Any] = {
            "cid": course_id,
            "size": 500,
            "prev": 0,
            "order": "earliest",
            "sample": False,
        }
        if chapter_ids:
            payload["chapter_ids"] = chapter_ids
        fetch = self._fetch(ARTICLE_LIST_URL, payload)
        data = fetch.response.get("data") or {}
        articles = data.get("list") if isinstance(data, dict) else None
        if not isinstance(articles, list):
            raise GeektimeApiError("文章列表接口未返回列表")
        return _combine_results(articles, fetch.response, [fetch])

    def _get_v3_article_detail(self, article_id: str, article_type: str) -> QueryResult:
        fetch = self._fetch(V3_DETAIL_URL, {"id": article_id})
        detail = _extract_v3_detail(fetch.response)
        if not detail:
            raise ResourceNotFoundError(f"未找到文章: {article_id}")
        return _combine_results(
            _normalize_v3_article(detail, article_type), fetch.response, [fetch]
        )

    def _fetch_catalog_type(
        self, course_type: str
    ) -> tuple[list[dict[str, Any]], list[tuple[str, FetchResult]]]:
        _validate_course_types([course_type])
        if course_type in STANDARD_COURSE_TYPES:
            definition = STANDARD_COURSE_TYPES[course_type]
            cursor: int | str = 1
            entries: list[dict[str, Any]] = []
            pages: list[tuple[str, FetchResult]] = []
            seen_cursors: set[str] = set()
            while True:
                payload = {
                    "tag_ids": [],
                    "product_type": definition["product_type"],
                    "product_form": definition["product_form"],
                    "pvip": 0,
                    "prev": cursor,
                    "size": 300,
                    "sort": 1,
                    "with_articles": True,
                }
                fetch = self._fetch(ALL_COURSE_URL, payload)
                pages.append((course_type, fetch))
                data = fetch.response.get("data") or {}
                products = data.get("products") if isinstance(data, dict) else None
                if not isinstance(products, list):
                    raise GeektimeApiError("全部课程接口未返回 products 列表")
                entries.extend(item for item in products if isinstance(item, dict))
                if not products:
                    break
                next_cursor = _next_cursor(data, cursor)
                if next_cursor is None or str(next_cursor) in seen_cursors:
                    break
                seen_cursors.add(str(cursor))
                cursor = next_cursor
            return entries, pages

        cursor = 0
        entries = []
        pages = []
        seen_cursors: set[str] = set()
        while True:
            payload = {"type": course_type, "size": 100, "prev": cursor, "orderby": "new"}
            fetch = self._fetch(V3_LIST_URL, payload)
            pages.append((course_type, fetch))
            data = fetch.response.get("data") or {}
            items = data.get("list") if isinstance(data, dict) else None
            if not isinstance(items, list):
                raise GeektimeApiError(f"{COURSE_TYPE_NAMES[course_type]}接口未返回 list 列表")
            entries.extend(item for item in items if isinstance(item, dict))
            if not items:
                break
            next_cursor = _next_cursor(data, cursor)
            if next_cursor is None or str(next_cursor) in seen_cursors:
                break
            seen_cursors.add(str(cursor))
            cursor = next_cursor
        return entries, pages

    def _fetch_purchased_courses(
        self,
    ) -> tuple[list[dict[str, Any]], list[tuple[str, FetchResult]]]:
        cursor: int | str = 0
        entries: list[dict[str, Any]] = []
        pages: list[tuple[str, FetchResult]] = []
        seen_cursors: set[str] = set()
        while True:
            payload = {
                "desc": True,
                "expire": 1,
                "last_learn": 0,
                "learn_status": 0,
                "prev": cursor,
                "size": 300,
                "sort": 1,
                "type": "",
                "with_learn_count": 1,
            }
            fetch = self._fetch(PURCHASED_COURSE_URL, payload)
            pages.append(("purchased", fetch))
            data = fetch.response.get("data") or {}
            items: Any = None
            if isinstance(data, dict):
                if isinstance(data.get("products"), list) and data["products"]:
                    items = data["products"]
                elif isinstance(data.get("list"), list):
                    items = data["list"]
                elif isinstance(data.get("products"), list):
                    items = data["products"]
            if not isinstance(items, list):
                raise GeektimeApiError("已购课程接口未返回 list 或 products 列表")
            entries.extend(item for item in items if isinstance(item, dict))
            if not items:
                break
            next_cursor = _next_cursor(data, cursor)
            if next_cursor is None or str(next_cursor) in seen_cursors:
                break
            seen_cursors.add(str(cursor))
            cursor = next_cursor
        return entries, pages

    def _fetch(self, url: str, payload: dict[str, Any]) -> FetchResult:
        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            status_code = int(response.status_code)
            if status_code >= 500:
                raise _TransientApiError(f"极客时间服务暂时不可用: HTTP {status_code}")
            try:
                parsed = response.json()
            except (ValueError, json.JSONDecodeError) as exc:
                raise GeektimeApiError(f"接口返回了无效 JSON: {url}") from exc

            if not isinstance(parsed, dict):
                raise GeektimeApiError(f"接口响应不是 JSON 对象: {url}")
            if _is_auth_error(status_code, parsed):
                raise AuthenticationError("未登录或登录凭据已过期，请先运行 'geektime login'")
            if status_code >= 400:
                raise GeektimeApiError(_api_error_message(parsed, f"请求失败: HTTP {status_code}"))
            if parsed.get("code") not in (None, 0):
                raise GeektimeApiError(_api_error_message(parsed, "极客时间接口返回业务错误"))

            fetched_at = self.cache.save(url, payload, parsed)
            return FetchResult(parsed, url, fetched_at)
        except AuthenticationError:
            raise
        except _TransientApiError as exc:
            cached = self.cache.load(url, payload)
            if cached is None:
                raise GeektimeApiError(str(exc)) from exc
            return FetchResult(
                cached["response"],
                url,
                str(cached.get("fetched_at") or ""),
                cached=True,
                stale=True,
            )
        except requests.RequestException as exc:
            cached = self.cache.load(url, payload)
            if cached is None:
                raise GeektimeApiError(f"网络请求失败: {exc}") from exc
            return FetchResult(
                cached["response"],
                url,
                str(cached.get("fetched_at") or ""),
                cached=True,
                stale=True,
            )

    def _candidate_course_types(self, course_id: str, course_type: str | None) -> list[str]:
        if course_type:
            _validate_course_types([course_type])
            return [course_type]
        indexed_type = self._indexed_course_type(course_id)
        if indexed_type in COURSE_TYPE_NAMES:
            return [indexed_type] + [item for item in COURSE_TYPE_NAMES if item != indexed_type]
        return list(COURSE_TYPE_NAMES)

    def _indexed_course_type(self, course_id: str) -> str | None:
        item = self.cache.load_index().get("courses", {}).get(str(course_id), {})
        return item.get("type") if isinstance(item, dict) else None

    def _indexed_article_type(self, article_id: str) -> str | None:
        item = self.cache.load_index().get("articles", {}).get(str(article_id), {})
        return item.get("type") if isinstance(item, dict) else None


def parse_legacy_response(
    response: str | bytes | bytearray | int, context: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse responses returned by the legacy downloader HTTP client."""
    if isinstance(response, int):
        return None, f"跳过 {context}: 接口返回状态码 {response}"
    if not isinstance(response, str | bytes | bytearray):
        return None, f"跳过 {context}: 接口响应类型异常 {type(response).__name__}"
    try:
        parsed = json.loads(response)
    except json.JSONDecodeError as exc:
        return None, f"跳过 {context}: JSON 解析失败 {exc}"
    if not isinstance(parsed, dict):
        return None, f"跳过 {context}: 接口响应不是 JSON 对象"
    if parsed.get("code") not in (None, 0):
        return None, f"跳过 {context}: 接口返回 code={parsed.get('code')}"
    return parsed, None


def _normalize_course(item: dict[str, Any], purchased: bool = False) -> dict[str, Any]:
    raw = _unwrap_product(item)
    course_type = _infer_course_type(raw)
    author = raw.get("author") or item.get("author") or {}
    author_name = author.get("name", "") if isinstance(author, dict) else str(author)
    article = raw.get("article") if isinstance(raw.get("article"), dict) else {}
    return {
        "id": _course_id(raw),
        "type": course_type,
        "type_name": COURSE_TYPE_NAMES.get(course_type, "unknown"),
        "title": str(raw.get("title") or item.get("title") or ""),
        "subtitle": str(raw.get("subtitle") or item.get("subtitle") or ""),
        "author": {"name": author_name},
        "media": {
            "audio": bool(raw.get("is_audio") or raw.get("include_audio")),
            "video": bool(raw.get("is_video") or course_type == "c3"),
        },
        "purchased": purchased,
        "article_id": str(article.get("id") or item.get("article_id") or ""),
    }


def _normalize_course_info(
    item: dict[str, Any], course_type: str, purchased: bool = False
) -> dict[str, Any]:
    raw = _unwrap_product(item)
    summary = _normalize_course(raw, purchased=purchased)
    author = raw.get("author") if isinstance(raw.get("author"), dict) else {}
    column = raw.get("column") if isinstance(raw.get("column"), dict) else {}
    cover = raw.get("cover") if isinstance(raw.get("cover"), dict) else {}
    intro_html = str(raw.get("intro_html") or raw.get("intro") or "")
    summary.update(
        {
            "type": course_type,
            "type_name": COURSE_TYPE_NAMES.get(course_type, "unknown"),
            "author": {
                "name": str(author.get("name") or ""),
                "intro": str(author.get("intro") or author.get("brief") or ""),
            },
            "intro_html": intro_html,
            "intro_markdown": html2text.html2text(intro_html) if intro_html else "",
            "cover": str(
                cover.get("lecture_horizontal")
                or cover.get("square")
                or cover.get("default")
                or ""
            ),
            "update_frequency": str(column.get("update_frequency") or ""),
            "unit": str(column.get("unit") or raw.get("unit") or ""),
        }
    )
    return summary


def _merge_dq_course_detail(course: dict[str, Any], detail: dict[str, Any]) -> dict[str, Any]:
    intro_html = str(detail.get("content") or "")
    course.update(
        {
            "subtitle": str(detail.get("subtitle") or course.get("subtitle") or ""),
            "intro_html": intro_html,
            "intro_markdown": html2text.html2text(intro_html) if intro_html else "",
            "cover": str((detail.get("cover") or {}).get("default") or course.get("cover") or ""),
            "author": {"name": str((detail.get("author") or {}).get("name") or ""), "intro": ""},
        }
    )
    return course


def _normalize_article(detail: dict[str, Any]) -> dict[str, Any]:
    content_html = str(detail.get("article_content") or "")
    hls_videos = detail.get("hls_videos") if isinstance(detail.get("hls_videos"), dict) else {}
    videos = []
    for quality, value in hls_videos.items():
        media = value if isinstance(value, dict) else {}
        videos.append(
            {
                "quality": str(quality),
                "url": str(media.get("url") or ""),
                "size": media.get("size"),
            }
        )
    return {
        "id": str(detail.get("id") or ""),
        "course_id": str(detail.get("cid") or detail.get("column_id") or detail.get("product_id") or ""),
        "chapter_id": str(detail.get("chapter_id") or ""),
        "type": _infer_course_type(detail),
        "title": str(detail.get("article_title") or ""),
        "subtitle": str(detail.get("article_subtitle") or ""),
        "summary": str(detail.get("article_summary") or ""),
        "author": {"name": str(detail.get("author_name") or "")},
        "published_at": detail.get("article_ctime"),
        "cover": str(detail.get("article_cover") or ""),
        "content_html": content_html,
        "content_markdown": html2text.html2text(content_html) if content_html else "",
        "neighbors": _normalize_neighbors(detail.get("neighbors")),
        "media": {
            "audio": [{"url": str(detail.get("audio_download_url") or "")}]
            if detail.get("audio_download_url")
            else [],
            "video": videos,
            "subtitles": _normalize_subtitles(detail.get("subtitles")),
        },
    }


def _normalize_v3_article(detail: dict[str, Any], article_type: str) -> dict[str, Any]:
    content_html = str(detail.get("content") or "")
    video = detail.get("video") if isinstance(detail.get("video"), dict) else {}
    medias = video.get("hls_medias") if isinstance(video.get("hls_medias"), list) else []
    return {
        "id": str(detail.get("id") or detail.get("article_id") or ""),
        "course_id": str(detail.get("product_id") or ""),
        "chapter_id": "",
        "type": article_type,
        "title": str(detail.get("title") or ""),
        "subtitle": str(detail.get("subtitle") or ""),
        "summary": str(detail.get("summary") or ""),
        "author": {"name": str((detail.get("author") or {}).get("name") or "")},
        "published_at": detail.get("ctime"),
        "cover": str((detail.get("cover") or {}).get("default") or ""),
        "content_html": content_html,
        "content_markdown": html2text.html2text(content_html) if content_html else "",
        "neighbors": {"left": None, "right": None},
        "media": {
            "audio": [],
            "video": [
                {
                    "quality": str(media.get("quality") or ""),
                    "url": str(media.get("url") or ""),
                    "size": media.get("size"),
                }
                for media in medias
                if isinstance(media, dict)
            ],
            "subtitles": _normalize_subtitles(detail.get("subtitles")),
        },
    }


def _extract_v3_detail(response: dict[str, Any]) -> dict[str, Any]:
    data = response.get("data")
    if not isinstance(data, dict):
        return {}
    info = data.get("info")
    return info if isinstance(info, dict) else {}


def _normalize_neighbors(value: Any) -> dict[str, Any]:
    neighbors = value if isinstance(value, dict) else {}
    result: dict[str, Any] = {}
    for direction in ("left", "right"):
        item = neighbors.get(direction)
        result[direction] = (
            {
                "id": str(item.get("id") or item.get("article_id") or ""),
                "title": str(item.get("article_title") or item.get("title") or ""),
            }
            if isinstance(item, dict) and item
            else None
        )
    return result


def _normalize_subtitles(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [
        {
            "language": str(item.get("language") or item.get("lang") or ""),
            "url": str(item.get("url") or ""),
        }
        for item in value
        if isinstance(item, dict)
    ]


def _unwrap_product(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("product", "course"):
        value = item.get(key)
        if isinstance(value, dict):
            merged = dict(item)
            merged.update(value)
            return merged
    return item


def _course_id(item: dict[str, Any]) -> str:
    raw = _unwrap_product(item)
    return str(raw.get("id") or raw.get("product_id") or item.get("product_id") or "")


def _infer_course_type(item: dict[str, Any]) -> str:
    raw = _unwrap_product(item)
    explicit = raw.get("type") or raw.get("product_type")
    if isinstance(explicit, str) and explicit in COURSE_TYPE_NAMES:
        return explicit
    if raw.get("is_dailylesson"):
        return "d"
    if raw.get("is_qconp"):
        return "q"
    if raw.get("is_opencourse") or explicit == 4:
        return "p"
    product_form = raw.get("product_form")
    if raw.get("is_video") or product_form == 2:
        return "c3"
    if explicit == 1 or product_form == 1 or raw.get("is_column"):
        return "c1"
    return str(explicit) if explicit not in (None, "") else "unknown"


def _next_cursor(data: Any, current: int | str) -> int | str | None:
    if not isinstance(data, dict):
        return None
    page = data.get("page") if isinstance(data.get("page"), dict) else {}
    if page.get("more") is False:
        return None
    for key in ("score", "next", "prev"):
        value = page.get(key)
        if value not in (None, "", current):
            return value
    if page.get("more") is True:
        try:
            return int(current) + 1
        except (TypeError, ValueError):
            return None
    return None


def _deduplicate_courses(courses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result = []
    for course in courses:
        key = (str(course.get("type")), str(course.get("id")))
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(course)
    return result


def _raw_page_for_course(
    pages: list[tuple[str, FetchResult]], course_id: str
) -> dict[str, Any] | None:
    for _, fetch in pages:
        data = fetch.response.get("data")
        if not isinstance(data, dict):
            continue
        products = data.get("products") if isinstance(data.get("products"), list) else []
        listing = data.get("list") if isinstance(data.get("list"), list) else []
        items = [*products, *listing]
        if not isinstance(items, list):
            continue
        if any(isinstance(item, dict) and _course_id(item) == course_id for item in items):
            return fetch.response
    return None


def _category_counts(
    courses: list[dict[str, Any]], selected_types: list[str]
) -> dict[str, Any]:
    categories = {
        course_type: {
            "name": COURSE_TYPE_NAMES[course_type],
            "count": sum(1 for course in courses if course.get("type") == course_type),
        }
        for course_type in selected_types
    }
    for course_type in sorted(
        {str(course.get("type")) for course in courses} - set(selected_types)
    ):
        categories[course_type] = {
            "name": COURSE_TYPE_NAMES.get(course_type, "unknown"),
            "count": sum(1 for course in courses if course.get("type") == course_type),
        }
    return categories


def _combine_results(
    data: Any,
    raw: Any,
    fetches: list[FetchResult],
    categories: dict[str, Any] | None = None,
) -> QueryResult:
    fetched_at = max((fetch.fetched_at for fetch in fetches), default=_utc_now())
    sources = list(dict.fromkeys(fetch.source for fetch in fetches))
    return QueryResult(
        data=data,
        raw=raw,
        sources=sources,
        fetched_at=fetched_at,
        cached=bool(fetches) and all(fetch.cached for fetch in fetches),
        stale=any(fetch.stale for fetch in fetches),
        categories=categories,
    )


def _validate_course_types(course_types: list[str]) -> None:
    invalid = [item for item in course_types if item not in COURSE_TYPE_NAMES]
    if invalid:
        raise ValueError(
            f"未知课程分类: {', '.join(invalid)}；可用值: {', '.join(COURSE_TYPE_NAMES)}"
        )


def _is_auth_error(status_code: int, response: dict[str, Any]) -> bool:
    if status_code in {401, 403}:
        return True
    error = response.get("error")
    error_code = error.get("code") if isinstance(error, dict) else None
    messages = [
        str(response.get("message") or ""),
        str(response.get("msg") or ""),
        str(error.get("msg") or "") if isinstance(error, dict) else str(error or ""),
    ]
    return error_code in {-2000, 401, 403} or any("登录" in message for message in messages)


def _api_error_message(response: dict[str, Any], fallback: str) -> str:
    error = response.get("error")
    if isinstance(error, dict):
        return str(error.get("msg") or error.get("message") or fallback)
    return str(response.get("message") or response.get("msg") or error or fallback)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
