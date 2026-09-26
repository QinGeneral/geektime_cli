"""通用工具函数"""

import time

import requests


def timestamp_to_time(timestamp: int) -> str:
    """将时间戳转换为日期字符串"""
    time_array = time.localtime(timestamp)
    return time.strftime("%Y-%m-%d", time_array)


def duration_to_string(duration: int) -> str:
    """将秒数转换为 HH:MM:SS 格式"""
    duration = int(duration)
    hour = duration // 3600
    minute = (duration % 3600) // 60
    second = duration % 60
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def read_from_file(file_name: str) -> str:
    """读取文本文件内容"""
    with open(file_name, encoding="utf-8") as f:
        return f.read()


def save_to_file(file_name: str, content: str) -> None:
    """保存内容到文本文件"""
    with open(file_name, "w", encoding="utf-8") as f:
        f.write(content)


def read_binary_from_file(file_name: str) -> bytes:
    """读取二进制文件内容"""
    with open(file_name, "rb") as f:
        return f.read()


def write_binary_to_file(file_name: str, content: bytes) -> None:
    """写入二进制文件内容"""
    with open(file_name, "wb") as f:
        f.write(content)


def download_file(url: str, path: str) -> None:
    """下载文件到指定路径"""
    try:
        with requests.get(url, stream=True) as r:
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)
    except Exception as e:
        print(f"下载文件异常 {e}: {url}")
