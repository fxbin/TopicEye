"""搜狐热搜 — https://v2.sohu.com/landing-page/statistics-hot-news"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from . import BROWSER_UA, BaseTrendingScraper, TrendingEntry, register_trending

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Referer": "https://www.sohu.com/",
    "Accept": "application/json, text/plain, */*",
}


@register_trending("sohu")
class SohuTrending(BaseTrendingScraper):
    SOURCE = "sohu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        # 尝试多个接口，按优先级
        fetchers = [
            self._fetch_statistics_hot_news,
            self._fetch_hot_news_api,
            self._fetch_homepage,
        ]
        for fetcher in fetchers:
            try:
                results = await fetcher(client)
                if results:
                    logger.info("sohu trending: fetched %d items via %s", len(results), fetcher.__name__)
                    return results
            except Exception as e:
                logger.debug("sohu %s failed: %s", fetcher.__name__, e)
                continue

        logger.warning("sohu trending: all sources failed")
        return []

    # ── URL1: statistics-hot-news ──────────────────────────────────
    async def _fetch_statistics_hot_news(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://v2.sohu.com/landing-page/statistics-hot-news"
        resp = await client.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # 可能是 list 或 dict
        items = data if isinstance(data, list) else data.get("data", data.get("list", []))
        if not isinstance(items, list) or not items:
            return []

        return self._parse_items(items)

    # ── URL2: hot-news API ─────────────────────────────────────────
    async def _fetch_hot_news_api(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://www.sohu.com/api/v2/news/hot-news?pageSize=30"
        resp = await client.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        # 尝试常见结构: data.news / data.list / data.items
        items: list = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("news", "list", "items", "data"):
                candidate = data.get(key)
                if isinstance(candidate, list) and candidate:
                    items = candidate
                    break

        if not items:
            return []

        return self._parse_items(items)

    # ── URL3: 解析首页 HTML ────────────────────────────────────────
    async def _fetch_homepage(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://www.sohu.com/"
        headers = {**_HEADERS, "Accept": "text/html,application/xhtml+xml"}
        resp = await client.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        html = resp.text

        # 尝试从页面 script 中提取热榜 JSON
        # 搜狐首页可能在 window.__INITIAL_STATE__ 或类似变量中嵌入数据
        items: list = []

        # 策略1: 查找嵌入的 JSON 数据块
        for pattern in (
            r"window\.__INITIAL_STATE__\s*=\s*(\{.+?\})\s*;?\s*</script>",
            r"window\.__NUXT__\s*=\s*(\{.+?\})\s*;?\s*</script>",
            r"__NEXT_DATA__\s*=\s*(\{.+?\})\s*</script>",
        ):
            match = re.search(pattern, html, re.DOTALL)
            if match:
                try:
                    json_data = json.loads(match.group(1))
                    extracted = self._extract_items_from_json(json_data)
                    if extracted:
                        items.extend(extracted)
                except (json.JSONDecodeError, ValueError):
                    pass

        # 策略2: 从 HTML 中解析热榜链接 (a 标签)
        if not items:
            items = self._parse_html_links(html)

        return self._parse_items(items) if not isinstance(items[0], dict) else items if items else []

    # ── 通用解析 ───────────────────────────────────────────────────
    def _parse_items(self, items: list) -> list[TrendingEntry]:
        results: list[TrendingEntry] = []
        for rank, item in enumerate(items, start=1):
            if not isinstance(item, dict):
                continue

            title = item.get("title") or item.get("name") or item.get("word") or item.get("text") or ""
            if isinstance(title, str):
                title = title.strip()
            if not title:
                continue

            # URL
            article_url = item.get("url") or item.get("link") or item.get("href") or item.get("shareUrl") or ""

            # viewCount → hot_value
            view_count = item.get("viewCount") or item.get("pv") or item.get("hot") or item.get("hotScore") or 0
            try:
                hot_val = int(view_count)
            except (ValueError, TypeError):
                hot_val = 0

            results.append(
                {
                    "title": title,
                    "rank": rank,
                    "url": article_url,
                    "hot_value": hot_val,
                    "hot_value_raw": str(view_count),
                    "trend": "stable",
                    "cover_url": item.get("coverUrl") or item.get("img") or item.get("pic") or "",
                    "extra": {
                        "source": item.get("source") or item.get("authorName") or "",
                        "news_id": item.get("newsId") or item.get("id") or item.get("_id") or "",
                    },
                }
            )

        return results

    # ── 从嵌套 JSON 中提取条目列表 ──────────────────────────────────
    def _extract_items_from_json(self, data: Any) -> list:
        """递归搜索 JSON 中包含 title 字段的 dict 列表。"""
        if isinstance(data, list):
            # 如果列表中元素都有 title，直接返回
            if data and isinstance(data[0], dict) and ("title" in data[0] or "name" in data[0]):
                return data
            # 递归
            for elem in data:
                found = self._extract_items_from_json(elem)
                if found:
                    return found
        elif isinstance(data, dict):
            for key in ("hotNews", "hot", "news", "items", "list", "data", "feeds"):
                candidate = data.get(key)
                if isinstance(candidate, list) and len(candidate) >= 3:  # noqa: SIM102
                    if isinstance(candidate[0], dict) and ("title" in candidate[0] or "name" in candidate[0]):
                        return candidate
            # 深一层
            for v in data.values():
                found = self._extract_items_from_json(v)
                if found:
                    return found
        return []

    # ── 从 HTML 中解析链接 ─────────────────────────────────────────
    def _parse_html_links(self, html: str) -> list:
        """简单的 HTML 解析: 提取含热榜特征的链接。"""
        items: list = []
        # 搜狐热榜通常在特定容器中
        for match in re.finditer(
            r'<a[^>]+href=["\'](https?://www\.sohu\.com/a/[^"\']+)["\'][^>]*>'
            r"[^<]*<[^>]*>([^<]{4,80})</[^>]*>",
            html,
        ):
            items.append(
                {
                    "title": match.group(2).strip(),
                    "url": match.group(1),
                    "viewCount": 0,
                }
            )
            if len(items) >= 30:
                break
        return items
