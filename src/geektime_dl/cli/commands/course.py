"""Read-only course query commands."""

from __future__ import annotations

import typer
from rich.markdown import Markdown
from rich.table import Table

from geektime_dl.cli.commands.query_helpers import (
    console,
    emit_query_result,
    parse_course_types,
    run_query,
    validate_output_options,
)
from geektime_dl.core.api import COURSE_TYPE_NAMES, GeektimeApi

app = typer.Typer(help="查询课程目录、介绍和章节", rich_markup_mode="rich")


@app.command("list")
def course_list(
    scope: str = typer.Option(
        "purchased", "--scope", help="课程范围：purchased(已购买) 或 all(全部)"
    ),
    course_type: str | None = typer.Option(
        None, "--type", help="课程分类，多个值用逗号分隔：c1,c3,p,d,q"
    ),
    json_output: bool = typer.Option(False, "--json", help="输出规范化 JSON"),
    raw_output: bool = typer.Option(False, "--raw", help="输出上游原始 JSON"),
) -> None:
    """拉取全部或已购买的课程列表。"""
    validate_output_options(json_output, raw_output)
    if scope not in {"all", "purchased"}:
        raise typer.BadParameter("可用值: purchased, all", param_hint="--scope")
    course_types = parse_course_types(course_type)
    result = run_query(lambda: GeektimeApi().list_courses(scope, course_types))
    emit_query_result(result, json_output, raw_output, _render_course_list)


@app.command("info")
def course_info(
    course_id: str = typer.Argument(..., help="课程 ID"),
    course_type: str | None = typer.Option(
        None, "--type", help="可选课程分类：c1,c3,p,d,q"
    ),
    json_output: bool = typer.Option(False, "--json", help="输出规范化 JSON"),
    raw_output: bool = typer.Option(False, "--raw", help="输出上游原始 JSON"),
) -> None:
    """拉取一门课程的介绍。"""
    validate_output_options(json_output, raw_output)
    selected = parse_course_types(course_type)
    if selected and len(selected) != 1:
        raise typer.BadParameter("课程介绍只能指定一个分类", param_hint="--type")
    result = run_query(
        lambda: GeektimeApi().get_course_info(course_id, selected[0] if selected else None)
    )
    emit_query_result(result, json_output, raw_output, _render_course_info)


@app.command("chapters")
def course_chapters(
    course_id: str = typer.Argument(..., help="课程 ID"),
    course_type: str | None = typer.Option(
        None, "--type", help="可选课程分类：c1,c3,p,d,q"
    ),
    json_output: bool = typer.Option(False, "--json", help="输出规范化 JSON"),
    raw_output: bool = typer.Option(False, "--raw", help="输出上游原始 JSON"),
) -> None:
    """拉取一门课程的章节列表。"""
    validate_output_options(json_output, raw_output)
    selected = parse_course_types(course_type)
    if selected and len(selected) != 1:
        raise typer.BadParameter("章节查询只能指定一个分类", param_hint="--type")
    result = run_query(
        lambda: GeektimeApi().list_chapters(course_id, selected[0] if selected else None)
    )
    emit_query_result(result, json_output, raw_output, _render_chapters)


def _render_course_list(courses: list[dict]) -> None:
    if not courses:
        console.print("[yellow]没有找到课程[/yellow]")
        return
    ordered_types = list(COURSE_TYPE_NAMES) + sorted(
        {str(course.get("type")) for course in courses} - set(COURSE_TYPE_NAMES)
    )
    for course_type in ordered_types:
        type_name = COURSE_TYPE_NAMES.get(course_type, f"未知分类 {course_type}")
        selected = [course for course in courses if course.get("type") == course_type]
        if not selected:
            continue
        table = Table(title=f"{type_name}（{len(selected)}）", show_lines=False)
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("课程")
        table.add_column("作者", style="green")
        table.add_column("媒体", style="magenta")
        table.add_column("已购", justify="center")
        for course in selected:
            media = course.get("media") or {}
            media_names = []
            if media.get("audio"):
                media_names.append("音频")
            if media.get("video"):
                media_names.append("视频")
            table.add_row(
                str(course.get("id") or ""),
                str(course.get("title") or ""),
                str((course.get("author") or {}).get("name") or ""),
                "/".join(media_names) or "图文",
                "✓" if course.get("purchased") else "",
            )
        console.print(table)


def _render_course_info(course: dict) -> None:
    console.print(f"[bold]{course.get('title') or ''}[/bold]")
    console.print(
        f"ID: [cyan]{course.get('id') or ''}[/cyan]  "
        f"分类: {course.get('type_name') or course.get('type') or 'unknown'}"
    )
    author = (course.get("author") or {}).get("name") or ""
    if author:
        console.print(f"作者: {author}")
    if course.get("subtitle"):
        console.print(str(course["subtitle"]))
    update = " ".join(
        item for item in [course.get("unit"), course.get("update_frequency")] if item
    )
    if update:
        console.print(f"更新: {update}")
    if course.get("cover"):
        console.print(f"封面: {course['cover']}")
    intro = str(course.get("intro_markdown") or "").strip()
    if intro:
        console.print()
        console.print(Markdown(intro))


def _render_chapters(data: dict) -> None:
    if data.get("standalone"):
        console.print(
            "[yellow]该分类是单篇课程，没有章节列表。[/yellow] "
            f"文章 ID: [cyan]{data.get('article_id') or '未知'}[/cyan]"
        )
        return
    chapters = data.get("chapters") or []
    if not chapters:
        console.print("[yellow]课程没有返回章节[/yellow]")
        return
    table = Table(title=f"课程 {data.get('course_id')} 的章节")
    table.add_column("序号", justify="right")
    table.add_column("章节 ID", style="cyan")
    table.add_column("标题")
    table.add_column("文章数", justify="right")
    for chapter in chapters:
        table.add_row(
            str(int(chapter.get("order") or 0) + 1),
            str(chapter.get("id") or ""),
            str(chapter.get("title") or ""),
            str(chapter.get("article_count") or 0),
        )
    console.print(table)
