"""登录命令"""

import typer
from rich.console import Console

app = typer.Typer(
    help="登录极客时间",
    rich_markup_mode="rich",
)

console = Console()


@app.callback(invoke_without_command=True)
def login(
    ctx: typer.Context,
    check: bool = typer.Option(
        False, "--check", "-c",
        help="仅检查当前登录状态",
    ),
) -> None:
    """登录极客时间账号

    启动 Chrome 浏览器进行登录，自动获取并保存 Cookie。
    使用 --check 仅检查当前登录状态。
    """
    if ctx.invoked_subcommand is not None:
        return

    from geektime_dl.core.http_client import http_client

    if check:
        console.print("[dim]正在检查登录状态...[/dim]")
        if http_client.is_logged_in():
            console.print("[green]✓[/green] 登录状态有效")
        else:
            console.print("[red]✗[/red] 未登录或登录已过期")
            console.print("[dim]请运行 'geektime login' 重新登录[/dim]")
            raise typer.Exit(1)
        return

    # 执行浏览器登录
    console.print("[bold]极客时间登录[/bold]\n")
    success = http_client.login_via_browser()

    if success:
        console.print("\n[green]✓[/green] 登录成功！凭据已保存")
    else:
        console.print("\n[red]✗[/red] 登录失败")
        raise typer.Exit(1)
