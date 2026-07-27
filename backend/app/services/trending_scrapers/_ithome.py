"""IT之家热榜 — RSS https://www.ithome.com/rss/"""

from __future__ import annotations

import logging
import re

import httpx

from . import BaseTrendingScraper, TrendingEntry, register_trending

logger = logging.getLogger(__name__)

_TITLE_PAT = re.compile(r"<title>(.*?)</title>", re.DOTALL)
_LINK_PAT = re.compile(r"<link>(.*?)</link>", re.DOTALL)


@register_trending("ithome")
class ITHomeTrending(BaseTrendingScraper):
    SOURCE = "ithome"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://www.ithome.com/rss/"
        headers = self._build_headers(Referer="https://www.ithome.com/")
        xml = await self._fetch_text(client, url, headers=headers)
        if xml is None:
            return []

        # 按条目拆分
        items = re.split(r"<item>", xml)[1:]  # 跳过 channel header
        results: list[TrendingEntry] = []
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
