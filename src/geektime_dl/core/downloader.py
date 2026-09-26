"""极客时间课程下载器

从 geektime_downloader.py 重构，将下载逻辑封装为类，支持配置参数注入。
"""

import os
import random
import shutil
import time

import html2text
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from geektime_dl.core.api import (
    ALL_COURSE_URL,
    ARTICLE_DETAIL_URL,
    ARTICLE_LIST_URL,
    CHAPTER_URL,
    COURSE_TYPE_NAMES,
    PURCHASED_COURSE_URL,
    STANDARD_COURSE_TYPES,
    V3_DETAIL_URL,
    V3_LIST_URL,
    parse_legacy_response,
)
from geektime_dl.core.http_client import http_client
from geektime_dl.core.m3u8 import download_m3u8_video
from geektime_dl.utils.config import DownloadConfig
from geektime_dl.utils.helpers import save_to_file, timestamp_to_time

console = Console()

ALL_BUY_COURSE_URL = PURCHASED_COURSE_URL

# 课程类型定义
COURSE_TYPES = [
    {"type": key, "name": COURSE_TYPE_NAMES[key], **definition}
    for key, definition in STANDARD_COURSE_TYPES.items()
]

D_Q_COURSE_TYPES = [
    {"type": key, "name": COURSE_TYPE_NAMES[key]} for key in ("d", "q")
]


class GeektimeDownloader:
    """极客时间课程下载器"""

    def __init__(self, config: DownloadConfig | None = None):
        self.config = config or DownloadConfig()
        self.download_dir = self.config.output_dir + os.sep

        # 根据配置设置音视频下载开关
        http_client.is_download_audio = not self.config.text_only
        http_client.is_download_video = not self.config.text_only

    def _load_json_response(self, response: str | bytes | bytearray | int, context: str) -> dict | None:
        """解析接口 JSON；HTTP 层失败时返回的是状态码。"""
        parsed, error = parse_legacy_response(response, context)
        if error:
            console.print(f"[yellow]{error}[/yellow]")
        return parsed

    def _sleep(self) -> None:
        """请求间隔休眠"""
        sleep_time = random.randint(
            self.config.interval_min, self.config.interval_max
        )
        console.print(f"[dim]休眠 {sleep_time}s 🌛🌛🌛[/dim]")
        time.sleep(sleep_time)

    # =========================================================================
    # 普通课程下载（专栏、视频课、公开课）
    # =========================================================================

    def download_all(self, course_types: list[str] | None = None, is_debug: bool = False) -> None:
        """下载所有课程

        Args:
            course_types: 要下载的课程类型列表，None 表示全部
            is_debug: 调试模式
        """
        start_time = time.time()
        total_downloaded = 0

        # 下载普通课程
        for course_type in COURSE_TYPES:
            if course_types and course_type["type"] not in course_types:
                continue

            console.print(f"\n[bold cyan]━━━ {course_type['name']} ━━━[/bold cyan]")
            type_dir = self.download_dir + course_type["name"] + os.sep
            os.makedirs(type_dir, exist_ok=True)

            page = 1
            while True:
                course_infos = self._get_all_course(
                    type_dir, course_type["product_type"], course_type["product_form"], page
                )
                if not course_infos:
                    console.print(f"[green]✓[/green] {course_type['name']} 下载完成")
                    break

                console.print(f"[dim]第 {page} 页，共 {len(course_infos)} 个课程[/dim]")

                for idx, course_info in enumerate(course_infos):
                    if self.config.limit > 0 and total_downloaded >= self.config.limit:
                        console.print(f"[yellow]已达到下载限制 ({self.config.limit})[/yellow]")
                        break
                    if is_debug and idx == 1:
                        break

                    console.print(
                        f"\n[bold]课程 {idx + 1}/{len(course_infos)}:[/bold] "
                        f"{course_info['title']}"
                    )
                    self._prepare_course(course_info)
                    self._clean_course(course_info)
                    self._get_chapter(course_info)
                    total_downloaded += 1

                if self.config.limit > 0 and total_downloaded >= self.config.limit:
                    break

                page += 1
                if len(course_infos) < 15 or is_debug:
                    break

            if is_debug:
                break

        # 下载每日一课/大厂案例课
        if not course_types or any(t in (course_types or []) for t in ["d", "q"]):
            self._download_d_q_courses(is_debug)

        elapsed = int(time.time() - start_time)
        console.print(f"\n[bold green]✓ 下载完成！[/bold green]共耗时 {elapsed}s")

    def _get_all_course(self, type_dir, product_type, product_form, page=0):
        """获取所有课程列表"""
        data = {
            "tag_ids": [],
            "product_type": product_type,
            "product_form": product_form,
            "pvip": 0,
            "prev": page,
            "size": 300,
            "sort": 1,
            "with_articles": True,
        }
        cache_file = f"{type_dir}{product_type}{product_form}{page}_course_list.json"
        response_text = http_client.post_with_cache(
            cache_file, ALL_COURSE_URL, data, force_remote=True
        )
        response_data = self._load_json_response(response_text, "课程列表")
        if not response_data:
            return []
        courses = response_data.get("data", {}).get("products")

        course_infos = []
        if courses is None:
            return course_infos
        for course in courses:
            course_dir = type_dir + course["title"] + os.sep
            cover_url = course["cover"]["lecture_horizontal"]
            course_infos.append({
                "course": course,
                "title": course["title"],
                "subtitle": course["subtitle"],
                "dir": course_dir,
                "id": course["id"],
                "cover_url": cover_url,
                "is_video": course["is_video"],
                "is_audio": course["is_audio"],
            })
        return course_infos

    def _prepare_course(self, course_info):
        """准备课程目录和介绍"""
        course = course_info["course"]
        course_dir = course_info["dir"]
        os.makedirs(course_dir, exist_ok=True)

        # 课程简介
        course_intro = f"# {course_info['title']}\n\n"
        course_intro += f"**{course_info['subtitle']}**\n\n"
        course_intro += course["column"]["unit"] + course["column"]["update_frequency"] + "\n\n"
        course_intro += f"作者：{course['author']['name']}\n\n"
        course_intro += html2text.html2text(course["intro_html"]) + "\n\n"
        course_intro += f"![](https:{course['share']['poster']})\n\n" if course["share"]["poster"].startswith("//") else f"![]({course['share']['poster']})\n\n"
        course_intro += f"![](https:{course['column']['catalog_pic_url']})\n\n" if course["column"]["catalog_pic_url"].startswith("//") else f"![]({course['column']['catalog_pic_url']})\n\n"
        save_to_file(course_dir + "课程简介.md", course_intro)
        save_to_file(course_dir + "课程简介.html", course["intro_html"])

        # 作者简介
        author_intro = f"# {course['author']['name']}\n\n"
        author_intro += course["author"]["intro"] + "\n\n"
        author_intro += f"![]({course['author']['avatar']})\n\n"
        author_intro += course["author"]["brief"]
        save_to_file(course_dir + "作者简介.md", author_intro)

        # 下载封面和头像
        if course_info["cover_url"]:
            http_client.download_image(course_info["cover_url"], course_dir + "cover.png")
        if course["author"]["avatar"]:
            http_client.download_image(course["author"]["avatar"], course_dir + "author.png")

    def _clean_course(self, course_info):
        """清理空目录"""
        course_dir = course_info["dir"]
        if not os.path.exists(course_dir):
            return
        for file in os.listdir(course_dir):
            file_path = os.path.join(course_dir, file)
            if os.path.isdir(file_path) and not os.listdir(file_path):
                os.rmdir(file_path)

    def _clean_not_match_chapter(self, course_dir, target_chapter_dirs):
        """清理不匹配的章节目录"""
        for file in os.listdir(course_dir):
            if file == "cache":
                continue
            file_path = os.path.join(course_dir, file) + os.sep
            if os.path.isdir(file_path) and file_path not in target_chapter_dirs:
                shutil.rmtree(file_path)

    def _get_chapter(self, course_info):
        """获取章节列表并下载所有文章"""
        data = {"cid": course_info["id"]}
        course_dir = course_info["dir"]
        response_text = http_client.post_with_cache(
            course_dir + "chapter_info.json", CHAPTER_URL, data, force_remote=True
        )
        response_data = self._load_json_response(response_text, f"{course_info['title']} 章节列表")
        if not response_data:
            return
        chapters = response_data.get("data") or []

        chapter_ids = []
        chapter_dirs = {}
        for index, chapter in enumerate(chapters):
            chapter_dir = course_dir + f"{index} {chapter['title']}" + os.sep
            os.makedirs(chapter_dir, exist_ok=True)
            chapter_ids.append(chapter["id"])
            chapter_dirs[chapter["id"]] = chapter_dir

        self._clean_not_match_chapter(course_dir, list(chapter_dirs.values()))
        self._sleep()
        self._get_article_list(course_info["id"], chapter_ids, chapter_dirs, course_dir)

    def _get_article_list(self, course_id, chapter_ids, chapter_dirs, course_dir):
        """获取文章列表并逐一下载"""
        data = {
            "cid": course_id,
            "size": 500,
            "prev": 0,
            "order": "earliest",
            "sample": False,
        }
        if chapter_ids:
            data["chapter_ids"] = chapter_ids

        content = http_client.post_with_cache(
            course_dir + "article_list.json", ARTICLE_LIST_URL, data, force_remote=True
        )
        response_data = self._load_json_response(content, "文章列表")
        if not response_data:
            return

        articles = response_data.get("data", {}).get("list") or []

        for index, article in enumerate(articles):
            article_chapter_id = article["chapter_id"]
            if not chapter_dirs or article_chapter_id not in chapter_dirs:
                article_parent_dir = course_dir
            else:
                article_parent_dir = chapter_dirs[article_chapter_id]

            article_title = article["article_title"].replace("/", "／").replace("\t", " ")

            # 检查是否已下载
            if (os.path.exists(article_parent_dir + article_title + ".md") and
                    os.path.exists(article_parent_dir + article_title + ".html")):
                if self.config.text_only or (
                    os.path.exists(article_parent_dir + article_title + "-高清.mp4") or
                    os.path.exists(article_parent_dir + article_title + "-超清.mp4")
                ):
                    console.print(f"[dim]跳过已下载: {article_title}[/dim]")
                    continue

            console.print(f"  文章 {index + 1}/{len(articles)}: {article_title}")
            self._get_article_detail(article["id"], article_parent_dir)

        self._sleep()

    def _get_article_detail(self, article_id, article_parent_dir):
        """获取并保存单篇文章"""
        data = {"id": article_id, "include_neighbors": True, "is_freelyread": True}
        response_json, is_cache = http_client.post_with_cache_find_result(
            article_parent_dir + str(article_id) + ".json",
            ARTICLE_DETAIL_URL, data
        )
        response_data = self._load_json_response(response_json, f"文章 {article_id} 详情")
        if not response_data:
            return
        article_detail = response_data.get("data")
        if not article_detail:
            console.print(f"[yellow]跳过 文章 {article_id} 详情: 接口未返回 data[/yellow]")
            return

        # 视频类课程
        if article_detail.get("product_type") == "c3":
            self._get_video_article_detail(article_id, article_parent_dir, article_detail)
            return

        article_title = article_detail["article_title"].replace("/", "／")
        article_file = article_parent_dir + article_title + ".md"
        article_file_html = article_parent_dir + article_title + ".html"

        # 构建文章内容
        article_content = f"# {article_detail['article_title']}\n\n"
        article_content += f"发布时间：{timestamp_to_time(article_detail['article_ctime'])}\n\n"
        article_content += f"作者：{article_detail['author_name']}\n\n"

        if article_detail.get("article_summary"):
            article_content += f"总结：{article_detail['article_summary']}\n\n"

        if "neighbors" in article_detail:
            left = article_detail["neighbors"].get("left", {})
            right = article_detail["neighbors"].get("right", {})
            if "article_title" in left:
                article_content += f"上一篇：{left['article_title']}\n"
            if "article_title" in right:
                article_content += f"下一篇：{right['article_title']}\n\n"

        article_content += f"![]({article_detail['article_cover']})\n\n"

        article_markdown = article_content
        if "article_content" in article_detail:
            article_content += article_detail["article_content"]
            article_markdown += html2text.html2text(article_detail["article_content"])

        # 下载音频
        if not self.config.text_only:
            audio_url = article_detail.get("audio_download_url", "")
            audio_file = article_parent_dir + article_title + ".mp3"
            if audio_url and not os.path.exists(audio_file):
                http_client.download_mp4(audio_url, audio_file)
                console.print(f"    [green]音频下载完成[/green]")

        save_to_file(article_file_html, article_content)
        save_to_file(article_file, article_markdown)
        console.print(f"    [green]文章保存完成[/green]")

        if not is_cache:
            self._sleep()

    def _get_video_article_detail(self, article_id, article_parent_dir, article_detail):
        """获取视频类文章详情"""
        article_title = article_detail["article_title"].replace("/", "／").replace("\t", " ")
        article_file = article_parent_dir + article_title + ".md"
        article_file_html = article_parent_dir + article_title + ".html"

        # 构建文章内容
        article_content = f"# {article_title}\n\n"
        article_content += f"发布时间：{timestamp_to_time(article_detail['article_ctime'])}\n\n"
        article_content += f"作者：{article_detail['author_name']}\n\n"

        if article_detail.get("article_summary"):
            article_content += f"总结：{article_detail['article_summary']}\n\n"

        if "neighbors" in article_detail:
            left = article_detail["neighbors"].get("left", {})
            right = article_detail["neighbors"].get("right", {})
            if "article_title" in left:
                article_content += f"上一篇：{left['article_title']}\n"
            if "article_title" in right:
                article_content += f"下一篇：{right['article_title']}\n\n"

        article_content += f"![]({article_detail['article_cover']})\n\n"
        article_content += f"时长：{article_detail.get('video_time', '')}\n\n"

        article_markdown = article_content
        if "article_content" in article_detail:
            article_html = article_detail["article_content"]
            article_content += article_html
            article_markdown += html2text.html2text(article_html)

        # 下载字幕和视频
        if not self.config.text_only:
            subtitles = article_detail.get("subtitles", [])
            if subtitles:
                sub_url = subtitles[0].get("url", "")
                sub_file = article_parent_dir + article_title + ".vtt"
                if sub_url and not os.path.exists(sub_file):
                    http_client.download_file(sub_url, sub_file)

            video_sizes = ["sd"]
            video_size_name = {"ld": "标清", "sd": "高清", "hd": "超清"}
            for size in video_sizes:
                if size in article_detail.get("hls_videos", {}):
                    video_url = article_detail["hls_videos"][size]["url"]
                    video_file = article_parent_dir + article_title + "-" + video_size_name[size] + ".mp4"
                    if video_url and not os.path.exists(video_file):
                        download_m3u8_video(video_url, video_file)
                        console.print(f"    [green]视频下载完成[/green]")

        save_to_file(article_file_html, article_content)
        save_to_file(article_file, article_markdown)
        console.print(f"    [green]文章保存完成[/green]")

    # =========================================================================
    # 每日一课 / 大厂案例课下载
    # =========================================================================

    def _download_d_q_courses(self, is_debug=False):
        """下载每日一课和大厂案例课"""
        for course_type in D_Q_COURSE_TYPES:
            console.print(f"\n[bold cyan]━━━ {course_type['name']} ━━━[/bold cyan]")
            type_dir = self.download_dir + course_type["name"] + os.sep
            os.makedirs(type_dir, exist_ok=True)

            page = 0
            prev = 0
            while True:
                result = self._get_d_q_course_list(type_dir, course_type["type"], prev)
                if not result:
                    break
                course_infos, prev_score = result
                if not course_infos:
                    console.print(f"[green]✓[/green] {course_type['name']} 下载完成")
                    break

                prev = prev_score
                console.print(f"[dim]第 {page} 页，共 {len(course_infos)} 个课程[/dim]")

                for idx, course_info in enumerate(course_infos):
                    if is_debug and idx == 1:
                        break
                    console.print(
                        f"\n[bold]课程 {idx + 1}/{len(course_infos)}:[/bold] "
                        f"{course_info['title']}"
                    )
                    self._prepare_d_q_course(course_info)
                    self._get_d_q_course_detail(course_info)

                page += 1
                if is_debug:
                    break

    def _get_d_q_course_list(self, type_dir, type_name, prev):
        """获取每日一课/大厂案例课列表"""
        data = {"type": type_name, "size": 100, "prev": prev, "orderby": "new"}
        response_text = http_client.post_with_cache(
            type_dir + "d_q_course_list.json", V3_LIST_URL, data, force_remote=True
        )
        response_data = self._load_json_response(response_text, f"{type_name} 课程列表")
        if not response_data:
            return None

        course_list = response_data.get("data", {}).get("list")
        prev_score = response_data.get("data", {}).get("page", {}).get("score", 0)

        if course_list is None:
            return None

        course_infos = []
        for course in course_list:
            title = course["title"].replace("|", "｜")
            course_dir = type_dir + title + os.sep
            course_infos.append({
                "course": course,
                "title": course["title"],
                "subtitle": course.get("subtitle", ""),
                "dir": course_dir,
                "id": course["id"],
                "article_id": course["article"]["id"],
                "cover_url": course["cover"].get("square", ""),
                "is_video": course.get("is_video", False),
                "is_audio": course.get("is_audio", False),
            })
        return course_infos, prev_score

    def _prepare_d_q_course(self, course_info):
        """准备每日一课/大厂案例课目录"""
        os.makedirs(course_info["dir"], exist_ok=True)

    def _get_d_q_course_detail(self, course_info):
        """下载每日一课/大厂案例课详情"""
        data = {"id": course_info["article_id"]}
        course_dir = course_info["dir"]
        response_text = http_client.post_with_cache(course_dir + "d_q_article_info.json", V3_DETAIL_URL, data)
        response_data = self._load_json_response(response_text, f"{course_info['title']} 详情")
        if not response_data:
            return
        video_detail = response_data.get("data", {}).get("info")
        if not video_detail:
            console.print(f"[yellow]跳过 {course_info['title']} 详情: 接口未返回 info[/yellow]")
            return

        article_title = video_detail["title"].replace("/", "／").replace("\t", " ")
        article_file = course_dir + article_title + ".md"

        article_content = f"# {article_title}\n\n"
        if "subtitle" in video_detail:
            article_content += video_detail["subtitle"] + "\n\n"
        article_content += f"发布时间：{timestamp_to_time(video_detail['ctime'])}\n\n"
        article_content += f"作者：{video_detail['author']['name']}\n\n"
        article_content += f"时长：{video_detail['video']['time']}\n\n"

        if video_detail.get("summary"):
            article_content += f"总结：{video_detail['summary']}\n\n"

        article_content += f"![]({video_detail['cover']['default']})\n\n"
        if "content" in video_detail:
            article_content += video_detail["content"]

        # 下载视频
        if not self.config.text_only:
            video_size_name = {"ld": "标清", "sd": "高清", "hd": "超清"}
            max_size = 0
            video_size_key = "hd"
            for video in video_detail["video"]["hls_medias"]:
                if video["size"] > max_size:
                    max_size = video["size"]
                    video_size_key = video["quality"]
            for video in video_detail["video"]["hls_medias"]:
                if video_size_key != video["quality"]:
                    continue
                video_url = video["url"]
                video_file = course_dir + article_title + "-" + video_size_name[video["quality"]] + ".mp4"
                if video_url and not os.path.exists(video_file):
                    download_m3u8_video(video_url, video_file)
                    console.print(f"    [green]视频下载完成[/green]")

        save_to_file(article_file, article_content)
        console.print(f"    [green]文章保存完成[/green]")
