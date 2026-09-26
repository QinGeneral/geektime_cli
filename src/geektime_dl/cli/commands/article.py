"""Read-only article query commands."""

from __future__ import annotations

import typer
from rich.markdown import Markdown

from geektime_dl.cli.commands.query_helpers import (
    console,
    emit_query_result,
    run_query,
    validate_output_options,
)
from geektime_dl.core.api import GeektimeApi

app = typer.Typer(help="查询文章详细内容", rich_markup_mode="rich")


@app.command("detail")
def article_detail(
    article_id: str = typer.Argument(..., help="文章 ID"),
    json_output: bool = typer.Option(False, "--json", help="输出规范化 JSON"),
    raw_output: bool = typer.Option(False, "--raw", help="输出上游原始 JSON"),
) -> None:
    """拉取某一篇文章的详细内容，不下载媒体文件。"""
    validate_output_options(json_output, raw_output)
    result = run_query(lambda: GeektimeApi().get_article_detail(article_id))
    emit_query_result(result, json_output, raw_output, _render_article)


def _render_article(article: dict) -> None:
    console.print(f"[bold]{article.get('title') or ''}[/bold]")
    console.print(
        f"文章 ID: [cyan]{article.get('id') or ''}[/cyan]  "
        f"课程 ID: {article.get('course_id') or '未知'}"
    )
    author = (article.get("author") or {}).get("name") or ""
    if author:
        console.print(f"作者: {author}")
    if article.get("published_at"):
        console.print(f"发布时间: {article['published_at']}")
    if article.get("summary"):
        console.print(f"摘要: {article['summary']}")

    neighbors = article.get("neighbors") or {}
    if neighbors.get("left"):
        console.print(f"上一篇: {neighbors['left'].get('title') or ''}")
    if neighbors.get("right"):
        console.print(f"下一篇: {neighbors['right'].get('title') or ''}")

    media = article.get("media") or {}
    for audio in media.get("audio") or []:
        if audio.get("url"):
            console.print(f"音频: {audio['url']}")
    for video in media.get("video") or []:
        if video.get("url"):
            console.print(f"视频[{video.get('quality') or 'unknown'}]: {video['url']}")
    for subtitle in media.get("subtitles") or []:
        if subtitle.get("url"):
            console.print(f"字幕[{subtitle.get('language') or 'unknown'}]: {subtitle['url']}")

    content = str(article.get("content_markdown") or "").strip()
    if content:
        console.print()
        console.print(Markdown(content))
