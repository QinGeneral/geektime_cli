"""导出命令"""


import typer
from rich.console import Console

app = typer.Typer(
    help="导出课程为 Markdown 或 PDF",
    rich_markup_mode="rich",
)

console = Console()


@app.command("markdown")
def export_markdown(
    course: str | None = typer.Option(
        None, "--course", "-c",
        help="课程名称（不指定则列出可用课程）",
    ),
    output_dir: str | None = typer.Option(
        None, "--output-dir", "-o",
        help="输出目录（默认为课程目录）",
    ),
    download_dir: str = typer.Option(
        "./GeekTime", "--download-dir", "-d",
        help="下载目录（用于查找已下载课程）",
    ),
) -> None:
    """导出课程为合并的 Markdown 文件

    [bold]示例：[/bold]

      geektime export markdown --course "Go语言核心36讲"
      geektime export markdown --course "Go语言核心36讲" -o ~/Documents
    """
    from geektime_dl.core.exporter import export_course_to_markdown
    from geektime_dl.utils.config import get_config

    if not download_dir:
        download_dir = get_config().download.output_dir

    if not course:
        _list_available_courses(download_dir)
        return

    course_dir = _find_course_dir(download_dir, course)
    if not course_dir:
        return

    export_course_to_markdown(course_dir, output_dir)


@app.command("pdf")
def export_pdf(
    course: str | None = typer.Option(
        None, "--course", "-c",
        help="课程名称（不指定则列出可用课程）",
    ),
    output_dir: str | None = typer.Option(
        None, "--output-dir", "-o",
        help="输出目录（默认为课程目录）",
    ),
    download_dir: str = typer.Option(
        "./GeekTime", "--download-dir", "-d",
        help="下载目录（用于查找已下载课程）",
    ),
) -> None:
    """导出课程为 PDF 文件

    [bold]示例：[/bold]

      geektime export pdf --course "Go语言核心36讲"
      geektime export pdf --course "Go语言核心36讲" -o ~/Documents
    """
    from geektime_dl.core.exporter import export_course_to_pdf
    from geektime_dl.utils.config import get_config

    if not download_dir:
        download_dir = get_config().download.output_dir

    if not course:
        _list_available_courses(download_dir)
        return

    course_dir = _find_course_dir(download_dir, course)
    if not course_dir:
        return

    export_course_to_pdf(course_dir, output_dir)


def _find_course_dir(download_dir: str, course_name: str) -> str | None:
    """查找课程目录"""
    from geektime_dl.core.exporter import list_courses

    courses = list_courses(download_dir)
    for c in courses:
        if c["name"] == course_name:
            return c["path"]

    # 模糊匹配
    matches = [c for c in courses if course_name in c["name"]]
    if len(matches) == 1:
        return matches[0]["path"]
    elif len(matches) > 1:
        console.print("[yellow]找到多个匹配的课程：[/yellow]")
        for m in matches:
            console.print(f"  [{m['type']}] {m['name']}")
        console.print("\n[dim]请使用完整课程名称[/dim]")
        return None

    console.print(f"[red]未找到课程: {course_name}[/red]")
    console.print("[dim]使用不带 --course 参数运行以查看可用课程[/dim]")
    return None


def _list_available_courses(download_dir: str) -> None:
    """列出可用的课程"""
    from geektime_dl.core.exporter import list_courses

    courses = list_courses(download_dir)
    if not courses:
        console.print("[yellow]未找到已下载的课程[/yellow]")
        console.print("[dim]请先运行 'geektime download' 下载课程[/dim]")
        return

    console.print("[bold]已下载的课程：[/bold]\n")
    current_type = None
    for c in sorted(courses, key=lambda x: x["type"]):
        if c["type"] != current_type:
            current_type = c["type"]
            console.print(f"\n[bold cyan]{current_type}[/bold cyan]")
        console.print(f"  {c['name']}")
