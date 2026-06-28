"""知乎热榜 — https://www.zhihu.com/api/v3/feed/topstory/hot-list-web"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, truncate_title
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)


@register_trending("zhihu")
class ZhihuTrending(BaseTrendingScraper):
    SOURCE = "zhihu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://www.zhihu.com/api/v3/feed/topstory/hot-list-web?limit=50&desktop=true"
        headers = self._build_headers(
            Referer="https://www.zhihu.com/hot",
            Accept="application/json",
        )
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
            return []

        items = data.get("data", [])
        if not items:
            logger.warning("zhihu trending: empty data")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items, start=1):
            target = item.get("target", {})
            title = target.get("title_area", {}).get("text", "").strip()
            if not title:
                continue

            metrics = target.get("metrics_area", {})
            hot_text = metrics.get("text", "")
            # 解析热度如 "2345 万热度" → 23450000
            hot_val = 0
            if hot_text:
                try:
                    import re

                    num_match = re.match(r"([\d.]+)\s*(万)?", hot_text)
                    if num_match:
                        val = float(num_match.group(1))
                        if num_match.group(2) == "万":
                            val *= 10000
                        hot_val = int(val)
                except (ValueError, TypeError):
                    pass

            link = normalize_zhihu_url(target.get("link", {}).get("url", ""))
            excerpt = target.get("excerpt_area", {}).get("text", "")

            # 趋势判断
            label = target.get("label_area", {})
            trend_val = "stable"
            if label.get("trend"):
                tv = label["trend"]
                if tv > 0:
                    trend_val = "up"
                elif tv < 0:
                    trend_val = "down"

            results.append(
                {
                    "title": truncate_title(title),
                    "rank": idx,
                    "url": link,
                    "hot_value": hot_val,
                    "hot_value_raw": hot_text,
                    "trend": trend_val,
                    "cover_url": target.get("image_area", {}).get("url", ""),
                    "extra": {
                        "excerpt": excerpt,
                    },
                }
            )

        logger.info("zhihu trending: fetched %d items", len(results))
        return results
