"""东方财富财经快讯 — https://newsapi.eastmoney.com/kuaixun/"""

from __future__ import annotations

import json
import logging
import re
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, truncate_title

logger = logging.getLogger(__name__)

_PAT = re.compile(r"var ajaxResult=(\{.*\})$", re.DOTALL)


@register_trending("eastmoney")
class EastmoneyTrending(BaseTrendingScraper):
    SOURCE = "eastmoney"
    CATEGORY = "finance"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_30_1_.html"
        headers = self._build_headers(Referer="https://finance.eastmoney.com/")
        text = await self._fetch_text(client, url, headers=headers)
        if text is None:
            return []
        try:
            m = _PAT.search(text.strip())
            if not m:
                logger.warning("eastmoney: regex match failed")
                return []
            data = json.loads(m.group(1))
        except Exception as e:
            logger.warning("eastmoney trending parse failed: %s", e)
            return []

        items = data.get("LivesList", [])
        if not items:
            logger.warning("eastmoney trending: empty LivesList")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items[:30], start=1):
            title = item.get("title", "").strip()
            if not title:
                continue
            url_w = item.get("url_w", "")
            comment_num = int(item.get("commentnum", 0))
            showtime = item.get("showtime", "")

            results.append(
                {
                    "title": truncate_title(title),
                    "rank": idx,
                    "url": url_w.replace("http://", "https://"),
                    "hot_value": comment_num,
                    "hot_value_raw": f"评论{comment_num}",
                    "trend": "up" if comment_num > 20 else "stable",
                    "extra": {
                        "digest": item.get("digest", "")[:100],
                        "showtime": showtime,
                    },
                }
            )

        logger.info("eastmoney trending: fetched %d items", len(results))
        return results
