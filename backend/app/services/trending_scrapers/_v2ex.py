"""V2EX 热门话题 — https://www.v2ex.com/api/topics/hot.json"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("v2ex")
class V2EXTrending(BaseTrendingScraper):
    SOURCE = "v2ex"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        try:
            resp = await client.get(
                "https://www.v2ex.com/api/topics/hot.json",
            )
            resp.raise_for_status()
            items = resp.json()
        except Exception as e:
            logger.warning("v2ex trending fetch failed: %s", e)
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items, start=1):
            title = item.get("title", "").strip()
            if not title:
                continue

            replies = item.get("replies", 0) or 0
            url = item.get("url", "")
            member = item.get("member", {})
            node = item.get("node", {})

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": url,
                    "hot_value": replies,
                    "hot_value_raw": str(replies),
                    "trend": "up" if replies > 50 else "stable",
                    "extra": {
                        "username": member.get("username", ""),
                        "node_name": node.get("name", ""),
                    },
                }
            )

        logger.info("v2ex trending: fetched %d items", len(results))
        return results
