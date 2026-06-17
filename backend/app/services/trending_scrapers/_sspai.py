"""少数派热门 — https://sspai.com/api/v1/article/index/page/get?limit=30&offset=0&type=hot_to_all"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("sspai")
class SspaiTrending(BaseTrendingScraper):
    SOURCE = "sspai"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://sspai.com/api/v1/article/index/page/get?limit=30&offset=0&type=hot_to_all"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Referer": "https://sspai.com/",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("sspai trending fetch failed: %s", e)
            return []

        raw_items = data.get("data", [])
        if not raw_items:
            logger.warning("sspai trending: empty data")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(raw_items[:30], start=1):
            title = item.get("title", "").strip()
            if not title:
                continue

            article_id = item.get("id", "")
            like_count = item.get("like_count", 0)
            comment_count = item.get("comment_count", 0)
            hot_value = like_count * 100 + comment_count * 10

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": f"https://sspai.com/post/{article_id}",
                    "hot_value": hot_value,
                    "hot_value_raw": f"赞{like_count} 评{comment_count}",
                    "trend": "up" if idx <= 5 else "stable",
                    "extra": {
                        "slug": item.get("slug", ""),
                        "like_count": like_count,
                        "comment_count": comment_count,
                    },
                }
            )

        logger.info("sspai trending: fetched %d items", len(results))
        return results
