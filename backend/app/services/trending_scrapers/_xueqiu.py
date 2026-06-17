"""雪球热帖 — https://xueqiu.com/statuses/hot/listV2.json"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("xueqiu")
class XueqiuTrending(BaseTrendingScraper):
    SOURCE = "xueqiu"
    CATEGORY = "finance"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://xueqiu.com/statuses/hot/listV2.json?since_id=-1&max_id=0&size=30"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "X-Requested-With": "XMLHttpRequest",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("xueqiu trending fetch failed: %s", e)
            return []

        items = data.get("items", [])
        if not items:
            logger.warning("xueqiu trending: empty items")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items[:30], start=1):
            title = (item.get("title") or "").strip()
            text = (item.get("text") or "").strip()
            if not title:
                title = text[:50].strip()

            if not title:
                continue

            target = item.get("target", "")
            like_count = int(item.get("like_count", 0))
            retweet_count = int(item.get("retweet_count", 0))
            reply_count = int(item.get("reply_count", 0))
            hot_value = like_count + retweet_count * 2 + reply_count * 3

            user_info = item.get("user") or {}
            screen_name = user_info.get("screen_name", "")

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": f"https://xueqiu.com/{target}" if target else "",
                    "hot_value": hot_value,
                    "hot_value_raw": (f"赞{like_count} 转{retweet_count} 评{reply_count}"),
                    "trend": "up" if hot_value > 100 else "stable",
                    "extra": {
                        "text": text[:200],
                        "retweet_count": retweet_count,
                        "reply_count": reply_count,
                        "like_count": like_count,
                        "screen_name": screen_name,
                    },
                }
            )

        logger.info("xueqiu trending: fetched %d items", len(results))
        return results
