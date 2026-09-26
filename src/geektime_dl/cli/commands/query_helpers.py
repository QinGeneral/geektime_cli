"""Shared helpers for read-only query commands."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import typer
from rich.console import Console

from geektime_dl.core.api import (
    COURSE_TYPE_NAMES,
    AuthenticationError,
    GeektimeApiError,
    QueryResult,
    ResourceNotFoundError,
)

console = Console()
error_console = Console(stderr=True)


def parse_course_types(value: str | None) -> list[str] | None:
    if not value:
        return None
    result = []
    for item in value.split(","):
        course_type = item.strip()
        if course_type and course_type not in result:
            result.append(course_type)
    invalid = [item for item in result if item not in COURSE_TYPE_NAMES]
    if invalid:
        raise typer.BadParameter(
            f"未知课程分类: {', '.join(invalid)}；可用值: {', '.join(COURSE_TYPE_NAMES)}",
            param_hint="--type",
        )
    return result or None


def validate_output_options(json_output: bool, raw_output: bool) -> None:
    if json_output and raw_output:
        raise typer.BadParameter("--json 和 --raw 不能同时使用")


def run_query(call: Callable[[], QueryResult]) -> QueryResult:
    try:
        return call()
    except AuthenticationError as exc:
        error_console.print(f"[red]认证失败：[/red]{exc}")
        raise typer.Exit(3) from exc
    except ResourceNotFoundError as exc:
        error_console.print(f"[red]未找到：[/red]{exc}")
        raise typer.Exit(4) from exc
    except GeektimeApiError as exc:
        error_console.print(f"[red]请求失败：[/red]{exc}")
        raise typer.Exit(1) from exc


def emit_query_result(
    result: QueryResult,
    json_output: bool,
    raw_output: bool,
    render_human: Callable[[Any], None],
) -> None:
    if raw_output:
        typer.echo(json.dumps(result.raw, indent=2, ensure_ascii=False))
        return
    if json_output:
        typer.echo(json.dumps(result.payload(), indent=2, ensure_ascii=False))
        return
    if result.stale:
        error_console.print(
            f"[yellow]网络不可用，正在展示 {result.fetched_at or '未知时间'} 的缓存数据。[/yellow]"
        )
    render_human(result.data)
