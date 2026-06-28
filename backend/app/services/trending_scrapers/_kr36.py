"""36氪人气榜 — https://36kr.com/hot-list/catalog"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, truncate_title

logger = logging.getLogger(__name__)


@register_trending("36kr")
class Kr36Trending(BaseTrendingScraper):
    SOURCE = "36kr"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://gateway.36kr.com/api/mis/nav/home/nav/rank/hot"
        headers = self._build_headers(
            Referer="https://36kr.com/hot-list/catalog",
            Accept="application/json",
        )
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
            return []

        items = data.get("data", {}).get("hotRankList", [])
        if not items:
            logger.warning("36kr trending: empty list")
            return []

        results: list[TrendingEntry] = []
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
                    "title": truncate_title(title),
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
