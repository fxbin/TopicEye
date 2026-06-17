"""豆瓣热搜 — https://m.douban.com/rexxar/api/v2/search/hots"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("douban")
class DoubanTrending(BaseTrendingScraper):
    SOURCE = "douban"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://m.douban.com/rexxar/api/v2/search/hots?ck="
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) "
                "Version/16.6 Mobile/15E148 Safari/604.1"
            ),
            "Referer": "https://m.douban.com/",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("douban trending fetch failed: %s", e)
            return []

        # 解析热搜话题
        items = data.get("gallery_topics") or data.get("topics") or []
        if not items:
            logger.warning("douban trending: empty items")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items, start=1):
            title = (item.get("title") or item.get("name", "")).strip()
            if not title:
                continue

            read_count = item.get("read_count", 0)
            try:
                hot_val = int(read_count)
            except (ValueError, TypeError):
                hot_val = 0

            url_val = item.get("url") or item.get("sharing_url", "")

            # 从 card_subtitle 提取浏览量文本
            subtitle = item.get("card_subtitle", "")
            hot_raw = ""
            if read_count:
                hot_raw = f"{read_count / 10000:.1f}万" if read_count >= 10000 else str(read_count)

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": url_val,
                    "hot_value": hot_val,
                    "hot_value_raw": hot_raw or subtitle,
                    "trend": "up" if hot_val > 50000 else "stable",
                    "extra": {
                        "type": item.get("type", ""),
                        "id": item.get("id", ""),
                    },
                }
            )

        logger.info("douban trending: fetched %d items", len(results))
        return results
