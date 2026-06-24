# -*- coding: utf-8 -*-
"""无限暖暖「版本内容一览」爬虫 — GitHub Actions 版

每天定时跑,从官网新闻 API 找"版本内容一览"类新闻,
下载正文图片到 images/{版本号}/,生成 manifest.json。

输出:
  manifest.json   — 版本元数据清单(插件拉取)
  images/{ver}/   — 按版本号分目录的图片
"""

import json
import os
import re
import sys
import io
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# ============ 配置 ============
BASE_URL = "https://infinitynikki.nuanpaper.com"
API_LIST = f"{BASE_URL}/api/news"
PAGE_SIZE = 50
OUT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # 仓库根目录
IMAGES_DIR = os.path.join(OUT_DIR, "images")
MAX_WORKERS = 8
TIMEOUT = 30
RETRY = 3
SLEEP_BETWEEN = 0.1

KEYWORDS = ["版本内容一览", "版本一览"]
CONTENT_IMG_DOMAINS = ["webstatic.papegames.com"]
SECTION_MAP = {0: "新闻", 1: "公告", 2: "活动"}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": BASE_URL,
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "zh-CN,zh;q=0.9",
}

BJ_TZ = timezone(timedelta(hours=8))


def safe_name(s: str, max_len: int = 50) -> str:
    s = re.sub(r'[\\/:*?"<>|\n\r\t]', "_", s)
    return s[:max_len]


def extract_version(title: str, news_id: int) -> str:
    """从标题提取版本号,如 "2.7版本" → "2.7"。"""
    m = re.search(r"(\d+\.\d+)\s*版本", title or "")
    if m:
        return m.group(1)
    return f"unknown_{news_id}"


def fetch_list_page(offset: int, limit: int = PAGE_SIZE) -> dict | None:
    url = f"{API_LIST}?offset={offset}&limit={limit}"
    for i in range(RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"  [重试 {i+1}/{RETRY}] {type(e).__name__}: {e}")
            time.sleep(1)
    return None


def fetch_detail_html(news_id: int) -> str | None:
    url = f"{BASE_URL}/news/{news_id}"
    for i in range(RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            r.encoding = "utf-8"
            return r.text
        except Exception as e:
            print(f"  [重试 {i+1}/{RETRY}] {type(e).__name__}: {e}")
            time.sleep(1)
    return None


def is_content_image(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return any(d in parsed.netloc for d in CONTENT_IMG_DOMAINS)
    except Exception:
        return False


def parse_detail(html: str, news_id: int) -> dict:
    soup = BeautifulSoup(html, "lxml")

    title_div = soup.find("div", class_=re.compile(r"NewsDetail_news-title"))
    title = title_div.get_text(strip=True) if title_div else None

    content_div = soup.find("div", class_=re.compile(r"NewsDetail_news-content"))

    img_urls = []
    if content_div:
        for img in content_div.find_all("img"):
            src = img.get("src", "").strip()
            if src and not src.startswith("data:") and is_content_image(src):
                img_urls.append(src)

    return {
        "id": news_id,
        "title": title,
        "images": img_urls,
    }


def download_image(url: str, save_path: str) -> bool:
    if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
        return True
    for i in range(RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
            r.raise_for_status()
            with open(save_path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return True
        except Exception as e:
            print(f"  [图片重试 {i+1}/{RETRY}] {type(e).__name__}: {e}")
            time.sleep(1)
    return False


def main():
    print("=" * 70)
    print(" 无限暖暖「版本内容一览」爬虫 (GitHub Actions)")
    print(f" 输出目录: {OUT_DIR}")
    print("=" * 70)

    # 1. 抓取全部新闻列表
    print("\n[1] 抓取新闻列表...")
    all_news = []
    offset = 0
    total = None
    while True:
        data = fetch_list_page(offset, PAGE_SIZE)
        if not data:
            break
        if total is None:
            total = data["data"]["total"]
        items = data["data"]["data"]
        if not items:
            break
        all_news.extend(items)
        offset += len(items)
        if offset >= total or len(items) < PAGE_SIZE:
            break
        time.sleep(SLEEP_BETWEEN)
    print(f"  ✓ 列表抓取完成: {len(all_news)} 条")

    # 2. 过滤"版本内容一览"
    targets = [
        item
        for item in all_news
        if any(kw in item.get("title", "") for kw in KEYWORDS)
    ]
    print(f"\n[2] 过滤关键词 → {len(targets)} 条")

    # 3. 抓取详情页 + 解析
    print(f"\n[3] 抓取 {len(targets)} 个详情页...")
    version_list = []

    def process_item(item):
        nid = item["id"]
        html = fetch_detail_html(nid)
        if not html:
            return None
        detail = parse_detail(html, nid)
        version = extract_version(detail.get("title", ""), nid)
        publish_time = item.get("publish_time", "")

        # 下载图片
        img_entries = []
        ver_dir = os.path.join(IMAGES_DIR, version)
        os.makedirs(ver_dir, exist_ok=True)

        for idx, url in enumerate(detail["images"]):
            parsed = urlparse(url)
            orig_name = os.path.basename(parsed.path)
            base, ext = os.path.splitext(orig_name)
            if not ext:
                ext = ".png"
            fname = f"{idx:02d}_{safe_name(base, 40)}{ext}"
            save_path = os.path.join(ver_dir, fname)
            ok = download_image(url, save_path)
            if ok:
                img_entries.append(
                    {
                        "filename": fname,
                        "url": url,
                        "index": idx,
                    }
                )

        return {
            "version": version,
            "news_id": nid,
            "title": detail.get("title", ""),
            "publish_date": publish_time[:10] if publish_time else "",
            "news_url": f"{BASE_URL}/news/{nid}",
            "images": img_entries,
        }

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = [ex.submit(process_item, item) for item in targets]
        for i, f in enumerate(as_completed(futures), 1):
            result = f.result()
            if result:
                version_list.append(result)
            if i % 5 == 0 or i == len(targets):
                print(f"  进度: {i}/{len(targets)}")

    # 按版本号倒序(最新在前);数字版本号优先于 unknown_
    def _sort_key(v):
        ver = v["version"]
        # 数字版本号(如 "2.7")转 tuple 排序,unknown_ 排到最后
        if re.match(r"^\d+\.\d+$", ver):
            parts = [int(x) for x in ver.split(".")]
            return (0, parts)  # (0, [...]) < (1, ...)
        return (1, [0])

    version_list.sort(key=_sort_key, reverse=True)

    # 4. 生成 manifest.json
    manifest = {
        "updated_at": datetime.now(BJ_TZ).strftime("%Y-%m-%dT%H:%M:%S%z"),
        "latest_version": version_list[0]["version"] if version_list else "",
        "versions": version_list,
    }

    manifest_path = os.path.join(OUT_DIR, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"\n[4] manifest.json 已生成: {len(version_list)} 个版本")

    total_imgs = sum(len(v["images"]) for v in version_list)
    print(f"  总图片: {total_imgs} 张")
    for v in version_list:
        print(f"    v{v['version']} ({v['publish_date']}): {len(v['images'])} 图")

    print("\n✓ 爬取完成")


if __name__ == "__main__":
    main()
