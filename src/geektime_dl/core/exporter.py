"""课程导出模块

支持导出为 Markdown 和 PDF 格式。
从 md_to_epub.py 重构。
"""

import os
import re

from rich.console import Console

from geektime_dl.utils.helpers import read_from_file, save_to_file

console = Console()


def _extract_number(s: str) -> int:
    """从字符串开头提取数字"""
    match = re.match(r"\d+", s)
    return int(match.group()) if match else 1000


def _get_all_md_files(directory: str) -> list[str]:
    """获取目录下所有 .md 文件"""
    files = os.listdir(directory)
    files = [item for item in files if item.endswith(".md")]
    files = sorted(files, key=_extract_number)
    return [os.path.join(directory, item) for item in files]


def export_course_to_markdown(course_dir: str, output_dir: str | None = None) -> str | None:
    """将课程导出为单个合并的 Markdown 文件

    Args:
        course_dir: 课程目录路径
        output_dir: 输出目录，默认为课程目录

    Returns:
        输出文件路径，或 None（如果失败）
    """
    course_name = os.path.basename(course_dir.rstrip("/"))
    if not output_dir:
        output_dir = course_dir

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{course_name}.md")

    # 收集所有章节目录
    chapter_dirs = []
    for item in sorted(os.listdir(course_dir), key=_extract_number):
        item_path = os.path.join(course_dir, item)
        if os.path.isdir(item_path) and item != "cache":
            chapter_dirs.append(item_path)

    # 收集所有 md 文件
    md_files = []

    # 先添加课程简介和作者简介
    intro_file = os.path.join(course_dir, "课程简介.md")
    author_file = os.path.join(course_dir, "作者简介.md")
    if os.path.exists(intro_file):
        md_files.append(intro_file)
    if os.path.exists(author_file):
        md_files.append(author_file)

    # 添加各章节的 md 文件
    for chapter_dir in chapter_dirs:
        md_files.extend(_get_all_md_files(chapter_dir))

    if not md_files:
        console.print(f"[yellow]未找到 Markdown 文件: {course_dir}[/yellow]")
        return None

    # 合并所有内容
    merged_content = ""
    for md_file in md_files:
        try:
            content = read_from_file(md_file)
            merged_content += content + "\n\n---\n\n"
        except Exception as e:
            console.print(f"[red]读取文件失败: {md_file}: {e}[/red]")

    save_to_file(output_file, merged_content)
    console.print(f"[green]✓[/green] Markdown 导出完成: {output_file}")
    return output_file


def export_course_to_pdf(course_dir: str, output_dir: str | None = None) -> str | None:
    """将课程导出为 PDF 文件

    先合并为 Markdown，再转换为 HTML，最后转为 PDF。

    Args:
        course_dir: 课程目录路径
        output_dir: 输出目录，默认为课程目录

    Returns:
        输出文件路径，或 None（如果失败）
    """
    course_name = os.path.basename(course_dir.rstrip("/"))
    if not output_dir:
        output_dir = course_dir

    os.makedirs(output_dir, exist_ok=True)
    output_file = os.path.join(output_dir, f"{course_name}.pdf")

    # 先导出为 markdown
    md_file = export_course_to_markdown(course_dir, output_dir)
    if not md_file:
        return None

    try:
        import markdown
        from weasyprint import HTML

        # Markdown → HTML
        md_content = read_from_file(md_file)
        html_content = markdown.markdown(
            md_content,
            extensions=["tables", "fenced_code", "codehilite", "toc"],
        )

        # 添加基础 CSS 样式
        styled_html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="utf-8">
    <style>
        body {{
            font-family: "PingFang SC", "Microsoft YaHei", "Helvetica Neue", sans-serif;
            font-size: 14px;
            line-height: 1.8;
            color: #333;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
        }}
        h1 {{ font-size: 24px; border-bottom: 2px solid #eee; padding-bottom: 10px; }}
        h2 {{ font-size: 20px; }}
        h3 {{ font-size: 16px; }}
        code {{ background: #f5f5f5; padding: 2px 6px; border-radius: 3px; font-size: 13px; }}
        pre {{ background: #f5f5f5; padding: 16px; border-radius: 6px; overflow-x: auto; }}
        pre code {{ background: none; padding: 0; }}
        img {{ max-width: 100%; height: auto; }}
        hr {{ border: none; border-top: 1px solid #eee; margin: 30px 0; }}
        table {{ border-collapse: collapse; width: 100%; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background: #f5f5f5; }}
    </style>
</head>
<body>
{html_content}
</body>
</html>"""

        # HTML → PDF
        HTML(string=styled_html).write_pdf(output_file)
        console.print(f"[green]✓[/green] PDF 导出完成: {output_file}")
        return output_file

    except ImportError as e:
        console.print(f"[red]缺少 PDF 导出依赖:[/red] {e}")
        console.print("请运行: pip install weasyprint markdown")
        return None
    except Exception as e:
        console.print(f"[red]PDF 导出失败:[/red] {e}")
        return None


def list_courses(download_dir: str) -> list[dict]:
    """列出已下载的课程

    Args:
        download_dir: 下载目录

    Returns:
        课程信息列表
    """
    courses = []
    if not os.path.exists(download_dir):
        return courses

    for type_dir_name in os.listdir(download_dir):
        type_dir = os.path.join(download_dir, type_dir_name)
        if not os.path.isdir(type_dir):
            continue

        for course_name in os.listdir(type_dir):
            course_dir = os.path.join(type_dir, course_name)
            if not os.path.isdir(course_dir) or course_name == "cache":
                continue

            courses.append({
                "name": course_name,
                "type": type_dir_name,
                "path": course_dir,
            })

    return courses
