"""B站热搜 — https://s.search.bilibili.com/main/hotword"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("bilibili")
class BilibiliTrending(BaseTrendingScraper):
    SOURCE = "bilibili"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://s.search.bilibili.com/main/hotword?limit=30"
        headers = self._build_headers(Referer="https://www.bilibili.com")
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
            return []

        word_list = data.get("list", [])
        if not word_list:
            logger.warning("bilibili trending: empty list")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(word_list, start=1):
            keyword = item.get("show_name", item.get("keyword", "")).strip()
            if not keyword:
                continue
            score = item.get("score", 0)
            try:
                hot_val = int(float(str(score)))
            except (ValueError, TypeError):
                hot_val = 0

            results.append(
                {
                    "title": keyword,
                    "rank": idx,
                    "url": f"https://search.bilibili.com/all?keyword={keyword}",
                    "hot_value": hot_val,
                    "hot_value_raw": str(score),
                    "trend": "up" if item.get("heat_score", 0) > 0 else "stable",
                    "cover_url": item.get("icon", ""),
                    "extra": {
                        "keyword": item.get("keyword", ""),
                        "goto_type": item.get("goto_type", ""),
                    },
                }
            )

        logger.info("bilibili trending: fetched %d items", len(results))
        return results
