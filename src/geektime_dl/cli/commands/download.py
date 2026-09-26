"""下载命令"""

from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    help="下载极客时间课程",
    rich_markup_mode="rich",
)

console = Console()


@app.callback(invoke_without_command=True)
def download(
    ctx: typer.Context,
    output_dir: Optional[str] = typer.Option(
        None, "--output-dir", "-o",
        help="下载目录（默认 ./GeekTime）",
    ),
    interval: Optional[int] = typer.Option(
        None, "--interval", "-i",
        help="接口请求间隔秒数（默认 3-5 秒随机）",
    ),
    limit: Optional[int] = typer.Option(
        None, "--limit", "-n",
        help="限制下载课程数量（默认不限制）",
    ),
    text_only: bool = typer.Option(
        False, "--text-only", "-t",
        help="仅下载图文，不下载音视频",
    ),
    course_type: Optional[str] = typer.Option(
        None, "--type",
        help="课程类型：c1(专栏), c3(视频课), p(公开课), d(每日一课), q(大厂案例课)",
    ),
    debug: bool = typer.Option(
        False, "--debug",
        help="调试模式（仅下载少量内容）",
    ),
) -> None:
    """下载极客时间已购课程

    默认下载全部已购课程。使用选项可以自定义下载行为。

    [bold]示例：[/bold]

      geektime download                      # 下载全部课程
      geektime download -n 3 -t              # 仅下载 3 个课程的图文
      geektime download -o ~/Downloads/GK    # 指定下载目录
      geektime download --type c1            # 仅下载专栏类课程
    """
    if ctx.invoked_subcommand is not None:
        return

    from geektime_dl.core.downloader import GeektimeDownloader
    from geektime_dl.core.http_client import http_client
    from geektime_dl.utils.config import DownloadConfig, get_config

    # 检查登录状态
    if not http_client.is_logged_in():
        console.print("[red]✗[/red] 未登录或登录已过期")
        console.print("[dim]请先运行 'geektime login' 登录[/dim]")
        raise typer.Exit(1)

    # 加载配置并覆盖命令行参数
    config = get_config().download

    if output_dir is not None:
        config.output_dir = output_dir
    if interval is not None:
        config.interval_min = interval
        config.interval_max = interval
    if limit is not None:
        config.limit = limit
    if text_only:
        config.text_only = True

    # 解析课程类型
    course_types = None
    if course_type:
        course_types = [ct.strip() for ct in course_type.split(",")]

    # 显示配置信息
    console.print("[bold]下载配置[/bold]")
    console.print(f"  下载目录: {config.output_dir}")
    console.print(f"  请求间隔: {config.interval_min}-{config.interval_max}s")
    if config.limit > 0:
        console.print(f"  下载限制: {config.limit} 个课程")
    if config.text_only:
        console.print(f"  模式: [yellow]仅图文[/yellow]")
    if course_types:
        console.print(f"  课程类型: {', '.join(course_types)}")
    console.print()

    # 开始下载
    downloader = GeektimeDownloader(config)
    downloader.download_all(course_types=course_types, is_debug=debug)
