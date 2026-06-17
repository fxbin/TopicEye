"""36氪人气榜 — https://36kr.com/hot-list/catalog"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("36kr")
class Kr36Trending(BaseTrendingScraper):
    SOURCE = "36kr"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        url = "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://36kr.com/hot-list/catalog",
            "Accept": "application/json",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("36kr trending fetch failed: %s", e)
            return []

        items = data.get("data", {}).get("hotRankList", [])
        if not items:
            logger.warning("36kr trending: empty list")
            return []

        results: List[TrendingEntry] = []
        for idx, item in enumerate(items[:30], start=1):
            title = item.get("widgetContent", {}).get("title", "").strip()
            if not title:
                title = item.get("title", "").strip()
            if not title:
                continue

            stat = item.get("widgetContent", {}).get("stat", {})
            pv = stat.get("pv", 0)
            try:
                hot_val = int(pv)
            except (ValueError, TypeError):
                hot_val = 0

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": f"https://36kr.com/p/{item.get('id', '')}",
                    "hot_value": hot_val,
                    "hot_value_raw": str(pv),
                    "trend": "stable",
                    "cover_url": item.get("widgetContent", {}).get("cover", ""),
                    "extra": {
                        "summary": item.get("widgetContent", {}).get("summary", ""),
                        "author": item.get("widgetContent", {}).get("author", {}).get("name", ""),
                    },
                }
            )

        logger.info("36kr trending: fetched %d items", len(results))
        return results
