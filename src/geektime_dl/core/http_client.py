"""极客时间 HTTP 客户端

合并自 downloader_basement/base_http_client.py 和 geektime_http_client.py。
处理登录、Cookie 管理、HTTP 请求、缓存等。
"""

import json
import os
import shutil
import time
from contextlib import suppress
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image
from rich.console import Console

from geektime_dl.utils.config import load_credentials, save_credentials
from geektime_dl.utils.helpers import read_from_file, save_to_file

console = Console()


class GeektimeHttpClient:
    """极客时间 HTTP 客户端"""

    header = {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
        "Connection": "keep-alive",
        "Content-Type": "application/json",
        "Origin": "https://time.geekbang.org",
        "Referer": "https://time.geekbang.org/column/article/669505",
        "Sec-Fetch-Dest": "empty",
        "Sec-Fetch-Mode": "cors",
        "Sec-Fetch-Site": "same-origin",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/114.0.0.0 Safari/537.36"
        ),
        "sec-ch-ua": '"Not.A/Brand";v="8", "Chromium";v="114", "Google Chrome";v="114"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"macOS"',
    }

    cache_dir = "./cache"
    home_page_url = (
        "https://account.geekbang.org/login"
        "?redirect=https%3A%2F%2Ftime.geekbang.org%2Fdashboard%2Fusercenter"
    )
    article_detail_url = "https://time.geekbang.org/serv/v1/article"
    login_validate_url = "https://time.geekbang.org/serv/v3/learn/product"
    chrome_app_path = "/Applications/Google Chrome.app"

    # 是否下载音频/视频
    is_download_audio = True
    is_download_video = True

    def __init__(self):
        # ``header`` is a class-level template; keep credentials isolated per client.
        self.header = dict(type(self).header)
        self._prepare_cache()
        self._load_saved_header()

    def _prepare_cache(self):
        """创建缓存目录"""
        if not os.path.exists(self.cache_dir):
            os.makedirs(self.cache_dir, exist_ok=True)

    def _load_saved_header(self):
        """从已保存的凭据加载 header"""
        saved = load_credentials()
        if saved:
            self.header = saved

    # =========================================================================
    # 登录相关
    # =========================================================================

    def login_via_browser(self, max_wait: int = 300, poll_interval: float = 3) -> bool:
        """通过浏览器登录获取 Cookie

        Returns:
            bool: 登录是否成功
        """
        try:
            from selenium import webdriver
        except ImportError:
            console.print("[red]错误：[/red]缺少 selenium 相关依赖")
            console.print("请运行: pip install selenium")
            return False

        if not Path(self.chrome_app_path).exists():
            console.print("[red]未找到 Chrome 浏览器[/red]")
            console.print(f"请确认 Chrome 安装在 {self.chrome_app_path}")
            return False

        console.print("[bold]正在启动 Chrome 浏览器...[/bold]")
        console.print("[dim]请在浏览器中完成登录[/dim]\n")

        driver = None
        original_header = dict(self.header)
        try:
            options = webdriver.ChromeOptions()
            # Selenium 4 自带 Selenium Manager，无需额外的驱动管理依赖。
            driver = webdriver.Chrome(options=options)
            driver.maximize_window()
            driver.get(self.home_page_url)

            console.print("[yellow]等待登录中... 请在浏览器中完成登录操作[/yellow]")
            console.print("[dim]登录成功后将自动验证 Cookie 并关闭浏览器[/dim]\n")

            deadline = time.monotonic() + max_wait
            last_cookie = ""
            while time.monotonic() < deadline:
                current_url = driver.current_url
                if self._is_geektime_page(current_url):
                    cookie_header = self._cookie_header(driver.get_cookies())
                    if cookie_header and cookie_header != last_cookie:
                        last_cookie = cookie_header
                        self.header = {**original_header, "Cookie": cookie_header}
                        if self._validate_header_by_request():
                            save_credentials(self.header)
                            return True
                        self.header = dict(original_header)
                time.sleep(poll_interval)
        except Exception as exc:
            self.header = original_header
            console.print(f"[red]浏览器登录失败：[/red]{exc}")
            return False
        finally:
            if driver is not None:
                with suppress(Exception):
                    driver.quit()

        self.header = original_header
        console.print("[red]登录超时或未获取到有效 Cookie[/red]")
        return False

    @staticmethod
    def _is_geektime_page(url: str) -> bool:
        """登录成功后会按登录地址中的 redirect 返回极客时间主站。"""
        try:
            parsed = urlparse(url)
        except (TypeError, ValueError):
            return False
        return parsed.scheme == "https" and parsed.hostname == "time.geekbang.org"

    @staticmethod
    def _cookie_header(cookies: list[dict]) -> str:
        """把 Selenium Cookie 列表转换为 requests 使用的 Cookie header。"""
        pairs = []
        for cookie in cookies:
            name = str(cookie.get("name") or "").strip()
            if not name or any(character in name for character in ";\r\n"):
                continue
            value = str(cookie.get("value") or "")
            if "\r" in value or "\n" in value:
                continue
            pairs.append(f"{name}={value}")
        return "; ".join(pairs)

    def is_logged_in(self) -> bool:
        """检查当前凭据是否有效"""
        saved = load_credentials()
        if not saved:
            return False
        self.header = saved
        return self._validate_header_by_request()

    def _validate_header_by_request(self) -> bool:
        """通过请求验证 header 是否有效"""
        response = self._test_login_request()
        if isinstance(response, str):
            try:
                parsed = json.loads(response)
                return parsed.get("code") == 0
            except (json.JSONDecodeError, KeyError):
                return False
        return False

    def _test_login_request(self) -> str | int:
        """请求需要账号身份的已购课程接口，用于验证 Cookie。"""
        param = {
            "desc": True,
            "expire": 1,
            "last_learn": 0,
            "learn_status": 0,
            "prev": 0,
            "size": 1,
            "sort": 1,
            "type": "",
            "with_learn_count": 1,
        }
        return self.post(self.login_validate_url, param)

    # =========================================================================
    # HTTP 请求
    # =========================================================================

    def get(self, url: str, params: dict) -> str | int:
        """GET 请求"""
        try:
            response = requests.get(url, headers=self.header, params=params)
        except requests.exceptions.SSLError:
            response = requests.get(url, headers=self.header, params=params, verify=False)

        if response.status_code == 200:
            return response.text
        else:
            console.print(f"[red]请求失败[/red] 错误码: {response.status_code}")
            return response.status_code

    def post(self, url: str, data: dict) -> str | int:
        """POST 请求"""
        try:
            response = requests.post(url, json=data, headers=self.header)
        except requests.exceptions.SSLError:
            response = requests.post(url, json=data, headers=self.header, verify=False)
        except requests.exceptions.ProxyError:
            response = requests.post(url, json=data, headers=self.header, verify=False)
            return ""

        if response.ok:
            return response.text
        else:
            console.print(f"[red]请求失败[/red] 错误码: {response.status_code}")
            return response.status_code

    # =========================================================================
    # 缓存相关
    # =========================================================================

    def get_cache_file_name(self, source_file_name: str) -> str:
        """将源文件名转换为缓存目录下的文件名"""
        directory, filename = os.path.split(source_file_name)
        directory = os.path.join(directory, "cache/")
        dest_file_name = os.path.join(directory, filename)
        if not os.path.exists(directory):
            os.makedirs(directory)
        if os.path.exists(source_file_name):
            shutil.move(source_file_name, dest_file_name)
        return dest_file_name

    def get_with_cache(self, json_file_name, url, params, force_remote=False):
        response_json, _ = self._request_with_cache(
            json_file_name, url, params, is_post=False, force_remote=force_remote
        )
        return response_json

    def post_with_cache(self, json_file_name, url, data, force_remote=False):
        response_json, _ = self._request_with_cache(
            json_file_name, url, data, is_post=True, force_remote=force_remote
        )
        return response_json

    def post_with_cache_find_result(self, json_file_name, url, data, force_remote=False):
        return self._request_with_cache(
            json_file_name, url, data, is_post=True, force_remote=force_remote
        )

    def _request_with_cache(self, json_file_name, url, data, is_post, force_remote):
        """带缓存的请求"""
        json_file_name = self.get_cache_file_name(json_file_name)

        response_json = "{}"
        is_find_cache = False

        if os.path.exists(json_file_name) and not force_remote:
            response_json = read_from_file(json_file_name)
            is_find_cache = True
        else:
            response_json = self.post(url, data) if is_post else self.get(url, data)
            if isinstance(response_json, str):
                save_to_file(json_file_name, response_json)
            is_find_cache = False

        return response_json, is_find_cache

    # =========================================================================
    # 文件下载
    # =========================================================================

    def download_file(self, url: str, path: str) -> None:
        """下载文件"""
        try:
            with requests.get(url, stream=True) as r:
                r.raise_for_status()
                with open(path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
        except Exception as e:
            console.print(f"[red]下载文件异常:[/red] {e}")

    def download_m3u8_video(self, m3u8_url: str, output_path: str) -> None:
        """下载 m3u8 视频"""
        if not self.is_download_video:
            return
        from geektime_dl.core.m3u8 import download_m3u8_video
        download_m3u8_video(url=m3u8_url, output_path=output_path)

    def download_mp4(self, url: str, output_path: str) -> None:
        """下载 MP4 视频"""
        if not self.is_download_video:
            return
        self.download_file(url, output_path)

    def download_audio(self, url: str, output_path: str) -> None:
        """下载音频"""
        if not self.is_download_audio:
            return
        self.download_file(url, output_path)

    def download_image(self, image_url: str, file_name: str) -> None:
        """下载图片"""
        if os.path.exists(file_name):
            return
        try:
            response = requests.get(image_url)
        except requests.exceptions.SSLError:
            response = requests.get(image_url, verify=False)
        try:
            img = Image.open(BytesIO(response.content))
            if "." not in file_name:
                file_name += ".jpg"
            if img.mode != "RGB":
                img = img.convert("RGB")
            img.save(file_name)
        except Exception as e:
            console.print(f"[red]保存图片异常:[/red] {e}")


# 全局客户端实例
http_client = GeektimeHttpClient()
