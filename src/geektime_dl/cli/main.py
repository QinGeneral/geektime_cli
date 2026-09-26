"""极客时间下载器 CLI 主入口

参考 notebooklm-mcp-cli 项目结构，使用 typer + rich 实现。
"""

import sys

import typer
from rich.console import Console

from geektime_dl import __version__
from geektime_dl.cli.commands.article import app as article_app
from geektime_dl.cli.commands.config import app as config_app
from geektime_dl.cli.commands.course import app as course_app
from geektime_dl.cli.commands.download import app as download_app
from geektime_dl.cli.commands.export import app as export_app
from geektime_dl.cli.commands.login import app as login_app

console = Console()
error_console = Console(stderr=True)

# 主应用
app = typer.Typer(
    name="geektime",
    help="极客时间课程下载器 - 支持登录、下载、导出课程",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# 注册子命令
app.add_typer(login_app, name="login", help="登录极客时间账号")
app.add_typer(download_app, name="download", help="下载已购课程")
app.add_typer(export_app, name="export", help="导出课程为 Markdown 或 PDF")
app.add_typer(config_app, name="config", help="管理下载配置")
app.add_typer(course_app, name="course", help="查询课程目录、介绍和章节")
app.add_typer(article_app, name="article", help="查询文章详细内容")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-v",
        help="显示版本号",
    ),
) -> None:
    """
    [bold]极客时间课程下载器[/bold]

    使用 'geektime <command> --help' 查看具体命令的帮助信息。

    [bold]快速开始：[/bold]

      1. geektime login          # 登录极客时间
      2. geektime download       # 下载全部课程
      3. geektime export pdf     # 导出为 PDF
    """
    if version:
        console.print(f"geektime-cli v{__version__}")
        raise typer.Exit()

    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


def cli_main():
    """CLI 入口点，包含错误处理"""
    try:
        app()
    except Exception as e:
        if isinstance(e, typer.Exit | SystemExit):
            raise
        error_console.print(f"\n[red]✗ 错误:[/red] {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli_main()
