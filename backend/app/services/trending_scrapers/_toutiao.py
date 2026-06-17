"""今日头条热榜 — https://www.toutiao.com/hot-event/hot-board/"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("toutiao")
class ToutiaoTrending(BaseTrendingScraper):
    SOURCE = "toutiao"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        url = "https://www.toutiao.com/hot-event/hot-board/?origin=toutiao_pc"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://www.toutiao.com/",
            "Accept": "application/json",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("toutiao trending fetch failed: %s", e)
            return []

        items = data.get("data", [])
        if not items:
            logger.warning("toutiao trending: empty data")
            return []

        results: List[TrendingEntry] = []
        for idx, item in enumerate(items[:50], start=1):
            title = item.get("Title", "").strip()
            if not title:
                continue
            hot_val = 0
            hot_raw = item.get("HotValue", "0")
            try:
                hot_val = int(str(hot_raw).replace(",", "").replace("_", ""))
            except (ValueError, TypeError):
                pass

            url_val = item.get("Url", "")
            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": url_val,
                    "hot_value": hot_val,
                    "hot_value_raw": str(hot_raw),
                    "trend": "up" if item.get("Label", "") else "stable",
                    "cover_url": item.get("Image", {}).get("url", "") if isinstance(item.get("Image"), dict) else "",
                    "extra": {
                        "cluster_id": item.get("ClusterId", ""),
                        "label": item.get("Label", ""),
                    },
                }
            )

        logger.info("toutiao trending: fetched %d items", len(results))
        return results
