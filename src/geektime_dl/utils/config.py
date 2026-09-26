"""配置管理模块

管理极客时间下载器的配置，包括下载目录、请求间隔、下载数量等。
配置存储在 ~/.geektime/config.json。
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from platformdirs import user_config_dir

CONFIG_DIR = Path(user_config_dir("geektime", ensure_exists=True))
CONFIG_FILE = CONFIG_DIR / "config.json"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
HEADER_FILE = CONFIG_DIR / "header.json"


@dataclass
class DownloadConfig:
    """下载配置"""

    # 下载目录
    output_dir: str = "./GeekTime"
    # 请求间隔最小秒数
    interval_min: int = 3
    # 请求间隔最大秒数
    interval_max: int = 5
    # 下载课程数量限制（0 = 不限制）
    limit: int = 0
    # 仅下载图文，不下载音视频
    text_only: bool = False


@dataclass
class AppConfig:
    """应用配置"""

    download: DownloadConfig = field(default_factory=DownloadConfig)


def get_config() -> AppConfig:
    """加载配置文件，如不存在则返回默认配置"""
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            download_data = data.get("download", {})
            download_config = DownloadConfig(**download_data)
            return AppConfig(download=download_config)
        except (json.JSONDecodeError, TypeError):
            return AppConfig()
    return AppConfig()


def save_config(config: AppConfig) -> None:
    """保存配置到文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(
        json.dumps(asdict(config), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def save_credentials(header: dict) -> None:
    """保存登录凭据（header 信息）"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    HEADER_FILE.write_text(
        json.dumps(header, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def load_credentials() -> dict | None:
    """加载登录凭据"""
    if HEADER_FILE.exists():
        try:
            return json.loads(HEADER_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, TypeError):
            return None
    return None


def credentials_exist() -> bool:
    """检查是否存在已保存的凭据"""
    return HEADER_FILE.exists()
