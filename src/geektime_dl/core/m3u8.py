"""M3U8 视频下载器

从 m3u8_downloader.py 迁移，处理 m3u8 视频流的下载和合并。
"""

import os
from contextlib import suppress

import m3u8
import requests
from Crypto.Cipher import AES

# 密钥缓存
_store_keys: dict[str, bytes] = {}
_store_key: bytes | None = None


def _get_key(key_url: str) -> bytes:
    """获取加密密钥（带缓存）"""
    if key_url in _store_keys:
        return _store_keys[key_url]
    try:
        r = requests.get(key_url)
    except requests.exceptions.SSLError:
        r = requests.get(key_url, verify=False)
    _store_keys[key_url] = r.content
    return r.content


def _download_m3u8_file(url: str, path: str) -> None:
    """下载 m3u8 文件"""
    r = requests.get(url)
    with open(path, "wb") as f:
        f.write(r.content)


def _parse_m3u8(path: str) -> list[str]:
    """解析 m3u8 文件，提取视频片段 URL"""
    with open(path) as f:
        lines = f.readlines()
        video_urls = []
        for line in lines:
            if line.startswith("#"):
                continue
            url = line.strip()
            if url:
                video_urls.append(url)
        return video_urls


def _download_ts(url: str, path: str, key) -> None:
    """下载并解密 ts 片段"""
    global _store_key

    cryptor = None
    if key is not None:
        key_content = _get_key(key) if isinstance(key, str) else _get_key(key.uri)
        if len(key_content) != 0:
            _store_key = key_content
        elif _store_key is not None:
            key_content = _store_key
        cryptor = AES.new(key_content, AES.MODE_CBC)

    try:
        r = requests.get(url)
    except requests.exceptions.ChunkedEncodingError:
        _download_ts(url, path, key)
        return

    with open(path, "wb") as f:
        if cryptor is not None:
            f.write(cryptor.decrypt(r.content))
        else:
            f.write(r.content)


def _clean_ts(filenames: list[str]) -> None:
    """清理 ts 文件"""
    for filename in filenames:
        if os.path.exists(filename):
            os.remove(filename)


def download_m3u8_video(url: str, output_path: str) -> None:
    """下载 m3u8 视频并合并为 mp4

    Args:
        url: m3u8 文件 URL
        output_path: 输出 mp4 文件路径
    """
    dir_path, file_name = os.path.split(output_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    m3u8_file_path = os.path.join(dir_path, "temp.m3u8")
    ts_dir_path = os.path.join(dir_path, "ts")
    if not os.path.exists(ts_dir_path):
        os.makedirs(ts_dir_path)

    # 下载 m3u8 文件
    _download_m3u8_file(url, m3u8_file_path)

    # 解析 m3u8 文件
    video_urls = _parse_m3u8(m3u8_file_path)
    video = m3u8.load(url)
    keys = video.keys

    # 下载 ts 片段
    ts_filenames = []
    video_ts_url_root = url.rsplit("/", 1)[0] + "/"
    for i, video_url in enumerate(video_urls):
        ts_filename = os.path.join(ts_dir_path, f"{i}.ts")
        print(f"TS：{output_path} 进度: {i}/{len(video_urls)}")
        _download_ts(
            video_url if "http" in video_url else video_ts_url_root + video_url,
            ts_filename,
            keys[i] if i < len(keys) else keys[0],
        )
        ts_filenames.append(ts_filename)

    # 构建 ffmpeg concat 命令
    concat_cmd = '"concat:'
    for ts_file in ts_filenames:
        concat_cmd += ts_file + "|"
    concat_cmd = concat_cmd[:-1] + '"'

    # 删除临时 m3u8 文件
    os.remove(m3u8_file_path)

    # 转义特殊字符
    safe_output = output_path
    for char in [" ", "&", "(", ")", "|", "<", ">", "，", "《", "》", "\t", "'"]:
        safe_output = safe_output.replace(char, f"\\{char}")
    safe_output = safe_output.replace('"', '\\"')

    # 使用 ffmpeg 合并
    os.system(f"ffmpeg -y -i {concat_cmd} -c copy {safe_output}")

    # 清理 ts 文件
    _clean_ts(ts_filenames)
    if os.path.exists(ts_dir_path):
        with suppress(OSError):
            os.removedirs(ts_dir_path)
