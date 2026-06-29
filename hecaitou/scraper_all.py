#!/usr/bin/env python3
"""
槽边往事博客全量爬虫 - 爬取 2026-04-22 所有文章并保存为 Markdown
"""

import os
import re
import time
import random
from datetime import datetime
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, NavigableString, Tag


BASE_URL = "https://www.hecaitou.com"
OUTPUT_DIR = "hecaitou\\articles"
MAX_RESULTS = 1000  # 每页最大文章数，Blogger 支持到 500

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}


def get_page(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return BeautifulSoup(resp.text, "html.parser")
    except requests.RequestException as e:
        print(f"  请求失败: {e}")
        return None


def delay(min_s=1, max_s=2):
    time.sleep(random.uniform(min_s, max_s))


def parse_date_str(date_str):
    """将日期字符串解析为 datetime 对象，失败返回 None"""
    if not date_str or date_str == "0000-00-00":
        return None
    try:
        return datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return None


def collect_article_urls(start_date=None, end_date=None):
    """通过 Blogger 分页遍历，收集指定时间范围内的文章 URL 及其日期
    
    Blogger 按时间倒序排列文章，因此：
    - 跳过晚于 end_date 的文章（继续翻页）
    - 收集在范围内的文章
    - 遇到早于 start_date 的文章时停止翻页
    """
    articles = {}  # url -> {title, date}
    page_url = f"{BASE_URL}/search?max-results={MAX_RESULTS}"

    page_num = 1
    hit_early_stop = False

    while page_url:
        print(f"\n[分页 {page_num}] {page_url}")
        soup = get_page(page_url)
        if not soup:
            break

        new_count = 0
        page_min_date = None  # 本页最早日期，用于提前终止

        for post in soup.select(".post-outer, .post"):
            # 提取文章链接
            title_elem = post.select_one(".post-title a, h2.post-title a, h3.post-title a")
            if not title_elem:
                continue
            href = title_elem.get("href", "")
            if not href or ".html" not in href:
                continue

            # 确保是绝对路径
            if href.startswith("/"):
                href = urljoin(BASE_URL, href)

            # 提取日期
            date_elem = post.select_one(".date-header, .post-timestamp, time.published, .timestamp-link")
            date_str = None
            if date_elem:
                raw = date_elem.get_text(strip=True)
                m = re.search(r"(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})", raw)
                if m:
                    date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

            # 从 URL 提取日期作为备用
            if not date_str:
                m = re.search(r"/(\d{4})/(\d{2})/", href)
                if m:
                    date_str = f"{m.group(1)}-{m.group(2)}-01"

            art_dt = parse_date_str(date_str)

            # 跟踪本页最早日期
            if art_dt:
                if page_min_date is None or art_dt < page_min_date:
                    page_min_date = art_dt

            # 时间范围过滤
            if end_date and art_dt and art_dt > end_date:
                continue  # 比结束时间新，跳过但继续
            if start_date and art_dt and art_dt < start_date:
                hit_early_stop = True
                break  # 比开始时间早，停止收集

            if href not in articles:
                articles[href] = {
                    "title": title_elem.get_text(strip=True),
                    "date": date_str,
                }
                new_count += 1

        print(f"  本页新增 {new_count} 篇，累计 {len(articles)} 篇")

        if hit_early_stop:
            print("  已到达开始时间边界，停止分页")
            break

        # 如果本页最早的日期已经早于 start_date，也无需继续翻页
        if start_date and page_min_date and page_min_date < start_date:
            print("  本页文章已早于开始时间，停止分页")
            break

        # 查找"较旧的博文"链接
        older_link = None
        for a in soup.select("a"):
            text = a.get_text(strip=True)
            if "较旧的博文" in text or "Older Posts" in text:
                older_link = a.get("href", "")
                if older_link.startswith("/"):
                    older_link = urljoin(BASE_URL, older_link)
                break

        if not older_link:
            print("  没有更多分页，遍历完成")
            break

        page_url = older_link
        page_num += 1
        delay()

    return articles


def html_to_markdown(elem):
    """将 HTML 元素递归转换为 Markdown 文本"""
    if isinstance(elem, NavigableString):
        return str(elem).strip()

    if not isinstance(elem, Tag):
        return ""

    lines = []

    for child in elem.children:
        if isinstance(child, Tag):
            tag = child.name
            if tag in ("p", "div"):
                text = child.get_text(strip=True)
                if text:
                    lines.append(text)
                    lines.append("")
            elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
                level = int(tag[1])
                text = child.get_text(strip=True)
                if text:
                    lines.append(f"{'#' * (level + 1)} {text}")
                    lines.append("")
            elif tag == "br":
                lines.append("")
            elif tag in ("ul", "ol"):
                for li in child.find_all("li", recursive=False):
                    text = li.get_text(strip=True)
                    if text:
                        lines.append(f"- {text}")
                lines.append("")
            elif tag == "blockquote":
                text = child.get_text(strip=True)
                if text:
                    for line in text.split("\n"):
                        lines.append(f"> {line.strip()}")
                    lines.append("")
            elif tag == "a":
                text = child.get_text(strip=True)
                href = child.get("href", "")
                if text and href:
                    lines.append(f"[{text}]({href})")
            elif tag == "img":
                src = child.get("src", "")
                alt = child.get("alt", "image")
                if src:
                    lines.append(f"![{alt}]({src})")
                    lines.append("")
            elif tag in ("script", "style", "iframe", "noscript"):
                continue
            else:
                text = html_to_markdown(child)
                if text.strip():
                    lines.append(text)
        elif isinstance(child, NavigableString):
            text = str(child).strip()
            if text:
                lines.append(text)

    return "\n".join(lines)


def extract_article(url):
    """提取单篇文章的标题、日期和正文"""
    soup = get_page(url)
    if not soup:
        return None

    # 标题
    title = ""
    for sel in ("h3.post-title", ".post-title", "h1.entry-title", "h2.post-title"):
        el = soup.select_one(sel)
        if el:
            title = el.get_text(strip=True)
            break
    if not title:
        el = soup.select_one("title")
        if el:
            title = el.get_text(strip=True).split(":")[0].split("|")[0].strip()

    # 日期
    date_str = None
    date_elem = soup.select_one(".date-header, .post-timestamp, time.published, .published")
    if date_elem:
        raw = date_elem.get_text(strip=True)
        m = re.search(r"(\d{4})[年/\-](\d{1,2})[月/\-](\d{1,2})", raw)
        if m:
            date_str = f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    if not date_str:
        m = re.search(r"/(\d{4})/(\d{2})/", url)
        if m:
            date_str = f"{m.group(1)}-{m.group(2)}-01"

    # 正文
    content = ""
    content_elem = soup.select_one(".post-body, .entry-content, .post-content, article")
    if content_elem:
        # 移除不需要的元素
        for remove in content_elem.select(
            "script, style, .post-footer, .comment-link, "
            ".post-share-buttons, .post-labels, .item-control"
        ):
            remove.decompose()
        content = html_to_markdown(content_elem)

    # 标签
    labels = []
    for el in soup.select(".post-labels a, .labels a, a[rel='tag']"):
        t = el.get_text(strip=True)
        if t and t not in labels:
            labels.append(t)

    return {
        "title": title,
        "date": date_str,
        "content": content,
        "labels": labels,
        "url": url,
    }


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|\r\n]', "", name)
    name = re.sub(r'\s+', " ", name).strip()
    return name[:80]


def save_article(article, output_dir):
    """保存文章为 Markdown 文件"""
    if not article.get("content"):
        print(f"  跳过（无内容）")
        return False

    date_str = article.get("date") or "0000-00-00"
    title = article.get("title") or "untitled"
    filename = f"{date_str}-{sanitize_filename(title)}.md"
    filepath = os.path.join(output_dir, filename)

    labels_str = ", ".join(article.get("labels", []))
    md = f"# {title}\n\n"
    md += f"- **日期**: {date_str}\n"
    md += f"- **链接**: {article['url']}\n"
    if labels_str:
        md += f"- **标签**: {labels_str}\n"
    md += f"\n---\n\n{article['content']}\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"  已保存: {filename}")
    return True


def parse_date_input(prompt):
    """解析用户输入的日期，支持 YYYY-MM-DD 和 YYYY/MM/DD 格式"""
    while True:
        raw = input(prompt).strip()
        if not raw:
            return None
        m = re.match(r"^(\d{4})[/\-](\d{1,2})[/\-](\d{1,2})$", raw)
        if not m:
            print("  日期格式错误，请输入 YYYY-MM-DD 或 YYYY/MM/DD，直接回车跳过")
            continue
        try:
            return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            print("  日期无效，请重新输入，直接回车跳过")
            continue


def main():
    print("=" * 60)
    print("槽边往事 全量文章爬虫")
    print(f"目标: {BASE_URL}")
    print("=" * 60)

    # 输入时间范围（可选）
    print("\n--- 时间范围设置（直接回车跳过则拉取全部） ---")
    start_date = parse_date_input("  开始时间 (YYYY-MM-DD): ")
    end_date = parse_date_input("  结束时间 (YYYY-MM-DD): ")

    if start_date or end_date:
        print(f"\n  拉取范围: {start_date or '不限'} ~ {end_date or '不限'}")

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 获取本地已有文件列表
    existing_files = set(os.listdir(OUTPUT_DIR)) if os.path.isdir(OUTPUT_DIR) else set()
    existing_count = len([f for f in existing_files if f.endswith(".md")])

    if existing_count > 0:
        print(f"\n  本地已有 {existing_count} 篇文章，已存在的文件将自动跳过")

    # 第一步：收集指定时间范围内的文章 URL
    print("\n[阶段1] 收集文章链接...")
    articles = collect_article_urls(start_date=start_date, end_date=end_date)
    print(f"\n共收集到 {len(articles)} 篇文章")

    if not articles:
        print("未找到符合条件的文章，退出")
        return

    # 按日期倒序排列
    sorted_urls = sorted(articles.keys(), key=lambda u: articles[u].get("date", ""), reverse=True)

    # 第二步：逐篇爬取正文
    print(f"\n[阶段2] 开始爬取正文内容...")
    saved = 0
    skipped_exist = 0
    skipped_other = 0

    for i, url in enumerate(sorted_urls, 1):
        info = articles[url]
        date_str = info.get("date") or "0000-00-00"
        title = info.get("title") or "untitled"

        # 检查本地是否已存在
        expected_filename = f"{date_str}-{sanitize_filename(title)}.md"
        if expected_filename in existing_files:
            print(f"\n[{i}/{len(sorted_urls)}] {title} ({date_str})")
            print(f"  跳过（本地已存在）")
            skipped_exist += 1
            continue

        print(f"\n[{i}/{len(sorted_urls)}] {title} ({date_str})")

        result = extract_article(url)
        if result:
            # 优先使用页面提取的信息
            if not result["title"]:
                result["title"] = title
            if not result["date"]:
                result["date"] = date_str
            result["url"] = url

            if save_article(result, OUTPUT_DIR):
                saved += 1
                existing_files.add(f"{result.get('date') or '0000-00-00'}-{sanitize_filename(result.get('title') or 'untitled')}.md")
            else:
                skipped_other += 1
        else:
            skipped_other += 1
            print(f"  跳过（获取失败）")

        delay(0.5, 1.5)

    print(f"\n{'=' * 60}")
    print(f"完成! 共保存 {saved} 篇文章到 {OUTPUT_DIR}/ 目录")
    if skipped_exist:
        print(f"跳过（已存在）{skipped_exist} 篇")
    if skipped_other:
        print(f"跳过（其他原因）{skipped_other} 篇")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
