from __future__ import annotations

import json

from typer.testing import CliRunner

from geektime_dl.cli.commands import article, course
from geektime_dl.cli.main import app
from geektime_dl.core.api import AuthenticationError, QueryResult, ResourceNotFoundError

runner = CliRunner()


def query_result(data, raw=None) -> QueryResult:
    return QueryResult(
        data=data,
        raw=raw if raw is not None else {"code": 0},
        sources=["https://example.test/api"],
        fetched_at="2026-08-28T00:00:00+00:00",
    )


def test_course_list_json_is_machine_readable(monkeypatch) -> None:
    class FakeApi:
        def list_courses(self, scope, course_types):
            assert scope == "all"
            assert course_types == ["c1", "c3"]
            return query_result(
                [
                    {
                        "id": "1",
                        "type": "c1",
                        "type_name": "专栏",
                        "title": "课程",
                        "author": {"name": "作者"},
                        "media": {"audio": True, "video": False},
                        "purchased": False,
                    }
                ]
            )

    monkeypatch.setattr(course, "GeektimeApi", FakeApi)
    result = runner.invoke(app, ["course", "list", "--scope", "all", "--type", "c1,c3", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data"][0]["id"] == "1"
    assert payload["source"] == ["https://example.test/api"]


def test_raw_output_has_no_normalized_wrapper(monkeypatch) -> None:
    class FakeApi:
        def get_article_detail(self, article_id):
            return query_result({}, raw={"code": 0, "data": {"id": int(article_id)}})

    monkeypatch.setattr(article, "GeektimeApi", FakeApi)
    result = runner.invoke(app, ["article", "detail", "8", "--raw"])

    assert result.exit_code == 0
    assert json.loads(result.stdout) == {"code": 0, "data": {"id": 8}}


def test_json_and_raw_are_mutually_exclusive() -> None:
    result = runner.invoke(app, ["course", "list", "--json", "--raw"])
    assert result.exit_code == 2
    assert "不能同时使用" in result.output


def test_authentication_error_uses_exit_code_3(monkeypatch) -> None:
    class FakeApi:
        def list_courses(self, scope, course_types):
            raise AuthenticationError("登录错误")

    monkeypatch.setattr(course, "GeektimeApi", FakeApi)
    result = runner.invoke(app, ["course", "list", "--json"])
    assert result.exit_code == 3
    assert "认证失败" in result.output


def test_not_found_uses_exit_code_4(monkeypatch) -> None:
    class FakeApi:
        def get_course_info(self, course_id, course_type):
            raise ResourceNotFoundError(course_id)

    monkeypatch.setattr(course, "GeektimeApi", FakeApi)
    result = runner.invoke(app, ["course", "info", "404", "--json"])
    assert result.exit_code == 4
    assert "未找到" in result.output


def test_daily_chapters_human_output_is_not_reported_as_empty(monkeypatch) -> None:
    class FakeApi:
        def list_chapters(self, course_id, course_type):
            return query_result(
                {
                    "course_id": course_id,
                    "course_type": "d",
                    "standalone": True,
                    "article_id": "99",
                    "chapters": [],
                }
            )

    monkeypatch.setattr(course, "GeektimeApi", FakeApi)
    result = runner.invoke(app, ["course", "chapters", "7", "--type", "d"])
    assert result.exit_code == 0
    assert "单篇课程" in result.stdout
    assert "99" in result.stdout
