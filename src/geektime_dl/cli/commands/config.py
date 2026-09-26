"""配置管理命令"""

from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    help="管理下载配置",
    rich_markup_mode="rich",
)

console = Console()

# 可配置的选项
CONFIG_KEYS = {
    "output_dir": "下载目录",
    "interval_min": "请求间隔最小秒数",
    "interval_max": "请求间隔最大秒数",
    "limit": "下载课程数量限制（0=不限制）",
    "text_only": "仅下载图文（true/false）",
}


@app.command("show")
def config_show() -> None:
    """显示当前配置"""
    from geektime_dl.utils.config import get_config, CONFIG_FILE

    config = get_config()

    table = Table(title="当前配置", show_header=True)
    table.add_column("配置项", style="cyan")
    table.add_column("值", style="green")
    table.add_column("说明", style="dim")

    table.add_row("output_dir", str(config.download.output_dir), "下载目录")
    table.add_row("interval_min", str(config.download.interval_min), "请求间隔最小秒数")
    table.add_row("interval_max", str(config.download.interval_max), "请求间隔最大秒数")
    table.add_row("limit", str(config.download.limit), "下载课程数量限制（0=不限制）")
    table.add_row("text_only", str(config.download.text_only), "仅下载图文")

    console.print(table)
    console.print(f"\n[dim]配置文件: {CONFIG_FILE}[/dim]")


@app.command("set")
def config_set(
    key: str = typer.Argument(..., help=f"配置项名称: {', '.join(CONFIG_KEYS.keys())}"),
    value: str = typer.Argument(..., help="配置值"),
) -> None:
    """设置配置项

    [bold]可用配置项：[/bold]

      output_dir     下载目录
      interval_min   请求间隔最小秒数
      interval_max   请求间隔最大秒数
      limit          下载课程数量限制（0=不限制）
      text_only      仅下载图文（true/false）

    [bold]示例：[/bold]

      geektime config set output_dir ~/Downloads/GeekTime
      geektime config set interval_min 5
      geektime config set text_only true
    """
    from geektime_dl.utils.config import get_config, save_config

    if key not in CONFIG_KEYS:
        console.print(f"[red]未知配置项: {key}[/red]")
        console.print(f"[dim]可用配置项: {', '.join(CONFIG_KEYS.keys())}[/dim]")
        raise typer.Exit(1)

    config = get_config()

    try:
        if key == "output_dir":
            config.download.output_dir = value
        elif key == "interval_min":
            config.download.interval_min = int(value)
        elif key == "interval_max":
            config.download.interval_max = int(value)
        elif key == "limit":
            config.download.limit = int(value)
        elif key == "text_only":
            config.download.text_only = value.lower() in ("true", "1", "yes")
    except ValueError:
        console.print(f"[red]无效的值: {value}[/red]")
        raise typer.Exit(1)

    save_config(config)
    console.print(f"[green]✓[/green] 已设置 {key} = {value}")


@app.command("reset")
def config_reset(
    confirm: bool = typer.Option(
        False, "--confirm", "-y",
        help="跳过确认提示",
    ),
) -> None:
    """重置为默认配置"""
    from geektime_dl.utils.config import AppConfig, save_config

    if not confirm:
        typer.confirm("确定要重置所有配置为默认值？", abort=True)

    save_config(AppConfig())
    console.print("[green]✓[/green] 配置已重置为默认值")
