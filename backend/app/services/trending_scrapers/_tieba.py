"""百度贴吧热议榜 — https://tieba.baidu.com/hottopic/browse/topiclist"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("tieba")
class TiebaTrending(BaseTrendingScraper):
    SOURCE = "tieba"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://tieba.baidu.com/hottopic/browse/topiclist"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/131.0.0.0 Safari/537.36"
            ),
            "Referer": "https://tieba.baidu.com/hottopic/browse/topiclist",
            "Accept": "application/json",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("tieba trending fetch failed: %s", e)
            return []

        # 预期 JSON 结构: {data: {bang: [{topic_name, topic_url, discuss_num}]}}
        bang_list = data.get("data", {}).get("bang", [])
        if not bang_list:
            logger.warning("tieba trending: no bang list")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(bang_list, start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("topic_name", "").strip()
            if not title:
                continue
            topic_url = item.get("topic_url", "")
            # discuss_num → hot_value
            discuss_num = item.get("discuss_num", "0")
            try:
                hot_val = int(str(discuss_num).replace(",", "").replace("_", ""))
            except (ValueError, TypeError):
                hot_val = 0

            results.append(
                {
                    "title": title,
                    "rank": idx,
                    "url": topic_url,
                    "hot_value": hot_val,
                    "hot_value_raw": str(discuss_num),
                    "trend": "stable",
                }
            )
            if len(results) >= 50:
                break

        logger.info("tieba trending: fetched %d items", len(results))
        return results
