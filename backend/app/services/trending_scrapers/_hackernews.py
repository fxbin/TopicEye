"""Hacker News Top — https://hacker-news.firebaseio.com/"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("hackernews")
class HackerNewsTrending(BaseTrendingScraper):
    SOURCE = "hackernews"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        ids_data = await self._fetch_json(
            client, "https://hacker-news.firebaseio.com/v0/topstories.json"
        )
        if ids_data is None:
            return []
        ids = ids_data[:30]

        results: list[TrendingEntry] = []
        for idx, item_id in enumerate(ids, start=1):
            try:
                item_resp = await client.get(
                    f"https://hacker-news.firebaseio.com/v0/item/{item_id}.json",
                )
                item_resp.raise_for_status()
                item = item_resp.json()
            except Exception:
                continue

            title = item.get("title", "").strip()
            if not title:
                continue

            score = item.get("score", 0)
            url = item.get("url", f"https://news.ycombinator.com/item?id={item_id}")

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": url,
                    "hot_value": score,
                    "hot_value_raw": str(score),
                    "trend": "up" if score > 100 else "stable",
                    "extra": {
                        "by": item.get("by", ""),
                        "descendants": item.get("descendants", 0),
                        "hn_link": f"https://news.ycombinator.com/item?id={item_id}",
                    },
                }
            )

        logger.info("hackernews trending: fetched %d items", len(results))
        return results
