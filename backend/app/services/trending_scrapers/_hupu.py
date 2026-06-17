"""虎扑热帖 — https://bbs.hupu.com/all-games"""

from __future__ import annotations

import logging
import re
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("hupu")
class HupuTrending(BaseTrendingScraper):
    SOURCE = "hupu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        # 虎扑步行街热帖 API
        url = "https://bbs.hupu.com/all-games"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://bbs.hupu.com/",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        except Exception as e:
            logger.warning("hupu trending fetch failed: %s", e)
            return []

        html = resp.text
        # 解析热帖列表
        # 匹配: <a href="/xxx.html" ...>标题</a>
        pattern = re.compile(
            r'<a[^>]*href="(/\d+\.html)"[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</a>',
            re.DOTALL,
        )

        results: List[TrendingEntry] = []
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
