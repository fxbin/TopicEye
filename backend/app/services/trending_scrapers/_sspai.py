"""少数派热门 — https://sspai.com/api/v1/article/index/page/get?limit=30&offset=0&type=hot_to_all"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, truncate_title

logger = logging.getLogger(__name__)


@register_trending("sspai")
class SspaiTrending(BaseTrendingScraper):
    SOURCE = "sspai"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://sspai.com/api/v1/article/index/page/get?limit=30&offset=0&type=hot_to_all"
        headers = self._build_headers(Referer="https://sspai.com/")
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
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
                    "title": truncate_title(title),
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
