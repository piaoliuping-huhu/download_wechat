#!/usr/bin/env python3
"""
金渐成博客爬虫 - 按主题爬取 https://www.jinjiancheng.com 所有文章及评论，保存为 Markdown
"""

import os
import re
import time
import random
import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.jinjiancheng.com"
OUTPUT_BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "articles")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
}

# 主题名称与 URL 路径映射
TOPICS = {
    "美股": "us-stocks",
    "港股": "hk-stocks",
    "加密货币": "crypto-bitcoin",
    "黄金": "gold",
    "房地产": "real-estate",
    "债务": "debt-crisis",
    "育儿": "parenting",
    "职场": "workplace",
    "A股": "a-shares",
}


def sanitize_filename(name):
    """清理文件名中的非法字符"""
    name = re.sub(r'[\\/:*?"<>|\r\n]', "", name)
    name = re.sub(r'\s+', " ", name).strip()
    return name[:80]


def get_page(url, retries=3):
    """获取页面 HTML"""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            print(f"  请求失败 (第{attempt+1}次): {e}")
            if attempt < retries - 1:
                time.sleep(2 * (attempt + 1))
    return None


def extract_article(html, url):
    """从文章页面提取标题、日期、正文、标签、公众号来源和评论"""
    soup = BeautifulSoup(html, "html.parser")

    # 标题: <h1>
    h1 = soup.select_one("h1")
    title = h1.get_text(strip=True) if h1 else "untitled"

    # 日期: 优先从 URL 中提取（最准确），其次从 <time> 标签获取
    date_str = None
    m = re.search(r"/(\d{4}-\d{2}-\d{2})", url)
    if m:
        date_str = m.group(1)
    if not date_str:
        article_elem = soup.select_one("article")
        if article_elem:
            header = article_elem.select_one("header")
            if header:
                time_elem = header.select_one("time")
                if time_elem:
                    date_str = time_elem.get_text(strip=True)

    # 公众号来源: 面包屑中的 /articles/{source} 链接
    source = ""
    for a in soup.select("header a"):
        href = a.get("href", "")
        if href.startswith("/articles/") and href.count("/") == 2:
            source = a.get_text(strip=True)
            break

    # 标签
    tags = []
    for a in soup.select("header a[href^='/topics/']"):
        tag_text = a.get_text(strip=True)
        if tag_text:
            tags.append(tag_text)
    for span in soup.select("header span.rounded"):
        span_text = span.get_text(strip=True)
        if span_text and span_text not in tags:
            tags.append(span_text)

    # 正文: <article> 中的 <div class="prose"> 或 <article> 内的所有内容
    article_elem = soup.select_one("article")
    body_html = ""
    if article_elem:
        prose = article_elem.select_one(".prose")
        if prose:
            body_html = str(prose)
        else:
            # 获取 article 中 header 之后的内容
            header = article_elem.select_one("header")
            if header:
                header.decompose()
            body_html = str(article_elem)

    # 评论: 提取完整的评论结构（读者提问 + 作者回复）
    # 页面结构：第1个 <article> 是正文，后续 <article> 是评论
    # 每个评论 article 内：
    #   - 读者区域：头像 + 用户名 + 地点 + <p>内容
    #   - 作者回复（可选）：<div role="list"> 内 <div role="listitem">，带 padding-left 缩进和"作者"徽章
    comments = []

    all_articles = soup.select("article")
    # 第1个 article 是正文，跳过
    for art in all_articles[1:]:
        comment_entry = {}

        # 1. 提取读者提问（article 的直接子 div 中第一层）
        reader_div = None
        for child in art.children:
            if hasattr(child, "name") and child.name == "div":
                # 找包含头像的 div（第一个直接的 div，不进入 role="list" 子区域）
                role_list = child.select_one('[role="list"]')
                if not role_list:
                    reader_div = child
                    break

        if reader_div:
            # 读者名
            reader_name_span = reader_div.select_one("header span")
            if reader_name_span:
                comment_entry["reader_name"] = reader_name_span.get_text(strip=True)

            # 读者地点
            reader_loc = ""
            header_spans = reader_div.select("header span")
            if len(header_spans) >= 2:
                loc_text = header_spans[1].get_text(strip=True)
                # 格式如 "· 北京"
                loc_text = loc_text.lstrip("· ").strip()
                if loc_text:
                    reader_loc = loc_text

            # 读者提问内容
            reader_p = reader_div.select_one("p")
            if reader_p:
                comment_entry["reader_text"] = reader_p.get_text(strip=True)

            if reader_loc:
                comment_entry["reader_loc"] = reader_loc

        # 2. 提取作者回复（在 role="list" > role="listitem" 中，带 padding-left 缩进）
        reply_listitems = art.select('[role="listitem"]')
        if reply_listitems:
            # 取第一个 listitem（通常只有一个作者回复）
            reply_div = reply_listitems[0]
            # 作者回复内容
            reply_p = reply_div.select_one("p")
            if reply_p:
                comment_entry["author_name"] = "金渐成"
                comment_entry["author_text"] = reply_p.get_text(strip=True)

        # 3. 如果读者没有名字但找到了 p 标签中的内容，尝试用备用方式
        if not comment_entry.get("reader_name") and comment_entry.get("reader_text"):
            # 从 article 中找第一个 span 作为读者名
            first_span = art.select_one("header span")
            if first_span:
                comment_entry["reader_name"] = first_span.get_text(strip=True)

        if comment_entry.get("reader_text") or comment_entry.get("author_text"):
            comments.append(comment_entry)

    return {
        "title": title,
        "date": date_str,
        "source": source,
        "tags": tags,
        "body_html": body_html,
        "comments": comments,
        "url": url,
    }


def html_to_markdown(html_str):
    """将 HTML 正文转为 Markdown，保留段落结构和内联格式"""
    soup = BeautifulSoup(html_str, "html.parser")

    lines = []

    def convert_inline(elem):
        """递归转换内联元素为 Markdown 格式"""
        if not hasattr(elem, "name") or elem.name is None:
            return elem.get_text() if hasattr(elem, 'get_text') else str(elem)

        tag = elem.name
        if tag == "strong" or tag == "b":
            return f"**{elem.get_text()}**"
        elif tag == "em" or tag == "i":
            return f"*{elem.get_text()}*"
        elif tag == "a":
            href = elem.get("href", "")
            text = elem.get_text(strip=True)
            if href and text:
                if href.startswith("/"):
                    href = BASE_URL + href
                return f"[{text}]({href})"
            return text
        elif tag == "code":
            return f"`{elem.get_text()}`"
        elif tag == "br":
            return "\n"
        elif tag == "img":
            src = elem.get("src", "")
            alt = elem.get("alt", "image")
            if src:
                if src.startswith("/"):
                    src = BASE_URL + src
                return f"![{alt}]({src})"
            return ""
        else:
            # 递归处理子元素
            result = []
            for child in elem.children:
                result.append(convert_inline(child))
            return "".join(result)

    def process_block(elem):
        """处理块级元素"""
        if not hasattr(elem, "name") or elem.name is None:
            return

        tag = elem.name

        if tag in ("p", "div"):
            # 保留段落内联格式
            text_parts = []
            for child in elem.children:
                text_parts.append(convert_inline(child))
            text = "".join(text_parts).strip()
            if text:
                lines.append(text)
                lines.append("")
        elif tag.startswith("h") and len(tag) == 2 and tag[1].isdigit():
            level = int(tag[1])
            text = elem.get_text(strip=True)
            if text:
                lines.append(f"{'#' * (level + 1)} {text}")
                lines.append("")
        elif tag in ("ul", "ol"):
            for li in elem.find_all("li", recursive=False):
                li_text = li.get_text(strip=True)
                if li_text:
                    lines.append(f"- {li_text}")
            lines.append("")
        elif tag == "blockquote":
            text = elem.get_text(strip=True)
            if text:
                for line in text.split("\n"):
                    lines.append(f"> {line.strip()}")
                lines.append("")
        elif tag == "img":
            src = elem.get("src", "")
            alt = elem.get("alt", "image")
            if src:
                if src.startswith("/"):
                    src = BASE_URL + src
                lines.append(f"![{alt}]({src})")
                lines.append("")
        elif tag in ("pre", "code"):
            text = elem.get_text(strip=True)
            if text:
                lines.append(f"```\n{text}\n```")
                lines.append("")
        elif tag == "hr":
            lines.append("---")
            lines.append("")
        elif tag == "figure":
            # 图片容器，提取内部 img
            img = elem.select_one("img")
            if img:
                src = img.get("src", "")
                alt = img.get("alt", "image")
                if src:
                    if src.startswith("/"):
                        src = BASE_URL + src
                    lines.append(f"![{alt}]({src})")
                    lines.append("")
            # 也提取 figcaption
            figcaption = elem.select_one("figcaption")
            if figcaption:
                cap = figcaption.get_text(strip=True)
                if cap:
                    lines.append(f"*{cap}*")
                    lines.append("")
        elif tag == "table":
            # 简单的表格转换
            rows = elem.select("tr")
            for row in rows:
                cells = row.select("td, th")
                cell_texts = [c.get_text(strip=True) for c in cells]
                lines.append("| " + " | ".join(cell_texts) + " |")
            lines.append("")
        else:
            # 递归处理子块级元素
            for child in elem.children:
                if hasattr(child, "name") and child.name:
                    process_block(child)

    # 处理所有块级子元素
    for elem in soup.children:
        if hasattr(elem, "name") and elem.name:
            process_block(elem)

    return "\n".join(lines)


def save_article(article, topic_dir):
    """保存文章为 Markdown 文件"""
    if not article.get("body_html"):
        return False

    date_str = article.get("date") or "0000-00-00"
    title = article.get("title") or "untitled"
    filename = f"{date_str}-{sanitize_filename(title)}.md"
    filepath = os.path.join(topic_dir, filename)

    # 正文转 Markdown
    body_md = html_to_markdown(article["body_html"])

    # 构建完整 Markdown
    md = f"# {title}\n\n"
    md += f"- **日期**: {date_str}\n"
    md += f"- **链接**: {article['url']}\n"
    if article.get("source"):
        md += f"- **来源**: {article['source']}\n"
    if article.get("tags"):
        md += f"- **标签**: {', '.join(article['tags'])}\n"
    md += f"\n---\n\n"
    md += body_md

    # 评论
    if article.get("comments"):
        md += f"\n\n---\n\n## 评论 ({len(article['comments'])} 条)\n\n"
        for i, comment in enumerate(article["comments"], 1):
            md += f"### {i}.\n\n"
            if comment.get("reader_text"):
                reader_name = comment.get("reader_name", "读者")
                reader_loc = comment.get("reader_loc", "")
                if reader_loc:
                    md += f"**{reader_name}**（{reader_loc}）:\n\n"
                else:
                    md += f"**{reader_name}**:\n\n"
                md += f"{comment['reader_text']}\n\n"
            if comment.get("author_text"):
                author_name = comment.get("author_name", "作者")
                md += f"> **{author_name}（回复）**:\n>\n"
                for line in comment['author_text'].split('\n'):
                    md += f"> {line}\n"
                md += "\n"

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(md)

    print(f"  已保存: {filename}")
    return True


def collect_articles_from_topic(topic_slug, topic_name):
    """收集指定主题下所有文章 URL
    
    该网站分页格式：
      第1页: /topics/{slug}
      第N页: /topics/{slug}/p/{N}
    注意：?page=N 参数无效，永远返回第1页！
    """
    articles = []
    seen_urls = set()
    page = 1
    max_consecutive_empty = 3  # 连续空页才停止
    empty_count = 0

    while True:
        if page == 1:
            url = f"{BASE_URL}/topics/{topic_slug}"
        else:
            url = f"{BASE_URL}/topics/{topic_slug}/p/{page}"
        print(f"  [分页 {page}] {url}")
        html = get_page(url)
        if not html:
            empty_count += 1
            if empty_count >= max_consecutive_empty:
                print(f"    连续 {max_consecutive_empty} 页无响应，停止")
                break
            page += 1
            time.sleep(random.uniform(1, 2))
            continue

        soup = BeautifulSoup(html, "html.parser")

        # 从 HTML 中提取文章链接：匹配 href="/articles/xxx/yyyy-mm-dd" 或 "/articles/xxx/yyyy-mm-dd-slug"
        new_count = 0
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            # 匹配文章链接格式：/articles/{作者}/{日期} 或 /articles/{作者}/{日期}-{标题}
            m = re.match(r'^/articles/([^/]+/(\d{4}-\d{2}-\d{2}))', href)
            if m:
                link = m.group(1)  # 如 "jinjiancheng/2026-06-21" 或 "jinjiancheng/2026-06-21-新选择"
                full_url = f"{BASE_URL}/articles/{link}"
                if full_url not in seen_urls:
                    seen_urls.add(full_url)
                    articles.append({"url": full_url, "slug": link})
                    new_count += 1

        print(f"    本页新增 {new_count} 篇，累计 {len(articles)} 篇")

        if new_count == 0:
            empty_count += 1
            # 如果当前页大于1且没有新文章，说明超出范围了
            if page > 1 and empty_count >= 1:
                print(f"    没有更多分页")
                break
        else:
            empty_count = 0  # 重置连续空页计数

        # 检查是否有下一页（查找 /p/{N} 格式的分页链接）
        has_next_page = False
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            m = re.search(rf'/topics/{re.escape(topic_slug)}/p/(\d+)', href)
            if m:
                p_num = int(m.group(1))
                if p_num > page:
                    has_next_page = True
                    break
        # 也检查"下一页"文字
        if not has_next_page:
            has_next_page = bool(soup.find(string=re.compile(r'下一页')))

        if not has_next_page:
            print(f"    没有更多分页")
            break

        page += 1
        time.sleep(random.uniform(1, 2))

    return articles


def crawl_topic(topic_name, topic_slug):
    """爬取指定主题下所有文章"""
    print(f"\n{'='*50}")
    print(f"主题: {topic_name} ({topic_slug})")
    print(f"{'='*50}")

    topic_dir = os.path.join(OUTPUT_BASE, topic_name)
    os.makedirs(topic_dir, exist_ok=True)

    # 收集文章 URL
    print("  [阶段1] 收集文章链接...")
    articles = collect_articles_from_topic(topic_slug, topic_name)
    print(f"  共收集到 {len(articles)} 篇文章")

    if not articles:
        return

    # 获取已有文件
    existing = set(os.listdir(topic_dir)) if os.path.isdir(topic_dir) else set()
    existing_md = [f for f in existing if f.endswith(".md")]
    if existing_md:
        print(f"  本地已有 {len(existing_md)} 篇文章，已存在的将跳过")

    # 逐篇爬取
    print(f"  [阶段2] 爬取文章内容...")
    saved = 0
    skipped_exist = 0
    skipped_other = 0

    for i, art in enumerate(articles, 1):
        url = art["url"]

        # 从 URL 提取日期和预判文件名
        m = re.search(r"/(\d{4}-\d{2}-\d{2})/", url)
        if not m:
            m = re.search(r"/(\d{4}-\d{2}-\d{2})$", url)
        date_part = m.group(1) if m else "0000-00-00"

        # 简单估算标题（从 slug）
        slug_title = art["slug"].split("/")[-1] if "/" in art["slug"] else art["slug"]

        # 检查是否已存在（模糊匹配）
        prefix = f"{date_part}-"
        if any(f.startswith(prefix) for f in existing):
            print(f"\n  [{i}/{len(articles)}] {url}")
            print(f"    跳过（本地已存在）")
            skipped_exist += 1
            continue

        print(f"\n  [{i}/{len(articles)}] {url}")

        html = get_page(url)
        if not html:
            skipped_other += 1
            continue

        article = extract_article(html, url)
        if article:
            if save_article(article, topic_dir):
                saved += 1
                # 更新 existing 集合
                date_str = article.get("date") or date_part
                title_str = article.get("title") or slug_title
                existing.add(f"{date_str}-{sanitize_filename(title_str)}.md")
            else:
                skipped_other += 1
        else:
            skipped_other += 1
            print(f"    跳过（提取失败）")

        time.sleep(random.uniform(0.5, 1.5))

    print(f"\n  {topic_name} 完成: 保存 {saved} 篇, 跳过(已存在) {skipped_exist} 篇, 跳过(其他) {skipped_other} 篇")


def main():
    print("=" * 60)
    print("金渐成博客爬虫 - https://www.jinjiancheng.com")
    print("=" * 60)

    print("\n可选主题:")
    for i, (name, slug) in enumerate(TOPICS.items(), 1):
        print(f"  {i}. {name} ({slug})")
    print("  0. 全部主题")

    choice = input("\n请选择主题 (输入数字，默认只爬取美股最新1篇用于测试): ").strip()

    # 测试模式：只爬美股最新1篇
    if not choice:
        print("\n[测试模式] 仅爬取美股分类最新1篇文章...")
        topic_dir = os.path.join(OUTPUT_BASE, "美股")
        os.makedirs(topic_dir, exist_ok=True)

        # 获取美股第1页第1篇文章
        html = get_page(f"{BASE_URL}/topics/us-stocks")
        if html:
            links = re.findall(r'/articles/([^/]+/\d{4}-\d{2}-\d{2})', html)
            if links:
                first_url = f"{BASE_URL}/articles/{links[0]}"
                print(f"  文章: {first_url}")
                art_html = get_page(first_url)
                if art_html:
                    article = extract_article(art_html, first_url)
                    if article:
                        save_article(article, topic_dir)
        return

    # 正常模式
    choice = int(choice)
    if choice == 0:
        topics_to_crawl = list(TOPICS.items())
    else:
        topic_list = list(TOPICS.items())
        if 1 <= choice <= len(topic_list):
            topics_to_crawl = [topic_list[choice - 1]]
        else:
            print("无效选择")
            return

    for topic_name, topic_slug in topics_to_crawl:
        crawl_topic(topic_name, topic_slug)

    print(f"\n{'=' * 60}")
    print(f"全部完成! 文件保存在 {OUTPUT_BASE}/")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    main()
