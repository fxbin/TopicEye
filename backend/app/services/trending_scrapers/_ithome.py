"""IT之家热榜 — RSS https://www.ithome.com/rss/"""

from __future__ import annotations

import logging
import re
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)

_TITLE_PAT = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_LINK_PAT = re.compile(r"<link>(.*?)</link>", re.DOTALL)


@register_trending("ithome")
class ITHomeTrending(BaseTrendingScraper):
    SOURCE = "ithome"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        url = "https://www.ithome.com/rss/"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://www.ithome.com/",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            xml = resp.text
        except Exception as e:
            logger.warning("ithome trending fetch failed: %s", e)
            return []

        # 按条目拆分
        items = re.split(r"<item>", xml)[1:]  # 跳过 channel header
        results: List[TrendingEntry] = []
        for idx, block in enumerate(items[:30], start=1):
            title_m = _TITLE_PAT.search(block)
            link_m = _LINK_PAT.search(block)
            if not title_m:
                continue
            title = title_m.group(1).strip()
            link = link_m.group(1).strip() if link_m else ""
            if not title:
                continue

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": link,
                    "hot_value": 0,
                    "hot_value_raw": "",
                    "trend": "stable",
                }
            )

        logger.info("ithome trending: fetched %d items", len(results))
        return results
