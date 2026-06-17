"""微博热搜 — https://s.weibo.com/top/summary

注意：需要有效的 SUB cookie 才能获取数据。
"""

from __future__ import annotations

import logging
import re
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry
import contextlib

logger = logging.getLogger(__name__)

# 正则匹配 <a href="/weibo?q=..."> 标题 </a> 后跟 <span> 热度 </span>
_PAT = re.compile(
    r'<a\s+href="/weibo\?q=([^"&]+)[^"]*band_rank=(\d+)[^"]*"[^>]*>'
    r"\s*([^<]+?)\s*</a>"
    r"\s*(?:<span>\s*(\d[\d,]*)\s*</span>)?",
    re.DOTALL,
)


@register_trending("weibo")
class WeiboTrending(BaseTrendingScraper):
    SOURCE = "weibo"
    CATEGORY = "hot"

    # 需要有效的微博 SUB cookie（从浏览器获取）
    _COOKIE = "SUB=_2AkMWIuNSf8NxqwJRmP8dy2rhaoV2ygrEieKgfhKJJRMxHRl-yT9jqk86tRB6PaLNvQZR6zYUcYVT1zSjoSreQHidcUq7"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        url = "https://s.weibo.com/top/summary?cate=realtimehot"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://s.weibo.com/",
            "Cookie": self._COOKIE,
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            html = resp.text
        except Exception as e:
            logger.warning("weibo trending fetch failed: %s", e)
            return []

        results: List[TrendingEntry] = []
        seen = set()
        for match in _PAT.finditer(html):
            query_encoded, rank_str, title, hot_str = match.groups()
            title = title.strip()
            if not title or title in seen:
                continue
            seen.add(title)

            try:
                rank = int(rank_str)
            except (ValueError, TypeError):
                rank = len(results) + 1

            hot_val = 0
            if hot_str:
                with contextlib.suppress(ValueError, TypeError):
                    hot_val = int(hot_str.replace(",", ""))

            decoded_query = query_encoded
            results.append(
                {
                    "title": title,
                    "rank": rank,
                    "url": f"https://s.weibo.com/weibo?q={decoded_query}",
                    "hot_value": hot_val,
                    "hot_value_raw": hot_str or "",
                    "trend": "up" if rank <= 5 else "stable",
                }
            )

        # 如果正则匹配不够，按 td-02 + a href 备用匹配
        if len(results) < 5:
            alt_pat = re.compile(
                r'<a\s+href="(/weibo\?q=[^"]+)"[^>]*target="_blank">([^<]+)</a>',
                re.DOTALL,
            )
            for match in alt_pat.finditer(html):
                href, title = match.groups()
                title = title.strip()
                if not title or title in seen:
                    continue
                seen.add(title)
                results.append(
                    {
                        "title": title,
                        "rank": len(results) + 1,
                        "url": f"https://s.weibo.com{href}",
                        "hot_value": 0,
                        "hot_value_raw": "",
                        "trend": "stable",
                    }
                )
                if len(results) >= 50:
                    break

        logger.info("weibo trending: fetched %d items", len(results))
        return results
