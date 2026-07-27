"""虎扑热帖 — https://bbs.hupu.com/all-games"""

from __future__ import annotations

import logging
import re

import httpx

from . import BaseTrendingScraper, TrendingEntry, register_trending

logger = logging.getLogger(__name__)


@register_trending("hupu")
class HupuTrending(BaseTrendingScraper):
    SOURCE = "hupu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        # 虎扑步行街热帖 API
        url = "https://bbs.hupu.com/all-games"
        headers = self._build_headers(Referer="https://bbs.hupu.com/")
        html = await self._fetch_text(client, url, headers=headers)
        if html is None:
            return []

        # 解析热帖列表
        # 匹配: <a href="/xxx.html" ...>标题</a>
        pattern = re.compile(
            r'<a[^>]*href="(/\d+\.html)"[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</a>',
            re.DOTALL,
        )

        results: list[TrendingEntry] = []
        seen = set()
        for match in pattern.finditer(html):
            href, title = match.groups()
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)
            results.append(
                {
                    "title": title,
                    "rank": len(results) + 1,
                    "url": f"https://bbs.hupu.com{href}",
                    "hot_value": 0,
                    "hot_value_raw": "",
                    "trend": "stable",
                }
            )
            if len(results) >= 30:
                break

        logger.info("hupu trending: fetched %d items", len(results))
        return results
