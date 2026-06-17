"""百度热搜 — https://top.baidu.com/board?tab=realtime"""

from __future__ import annotations

import logging
from typing import Any, List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)


@register_trending("baidu")
class BaiduTrending(BaseTrendingScraper):
    SOURCE = "baidu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> List[TrendingEntry]:
        url = "https://top.baidu.com/api/board?platform=wise&tab=realtime"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            "Referer": "https://top.baidu.com/board?tab=realtime",
            "Accept": "application/json",
        }
        try:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("baidu trending fetch failed: %s", e)
            return []

        cards = data.get("data", {}).get("cards", [])
        if not cards:
            logger.warning("baidu trending: no cards")
            return []

        results: List[TrendingEntry] = []
        rank = 0
        for card in cards:
            # cards 可能嵌套: card.content[0].content 才是列表
            outer_content = card.get("content", [])
            items = []
            if isinstance(outer_content, list):
                for section in outer_content:
                    if isinstance(section, dict) and "content" in section:
                        inner = section.get("content", [])
                        if isinstance(inner, list):
                            items.extend(inner)
                    elif isinstance(section, dict) and "word" in section:
                        items.append(section)
                    elif isinstance(section, list):
                        items.extend(section)
            if not items:
                items = outer_content if isinstance(outer_content, list) else []

            for item in items:
                if not isinstance(item, dict):
                    continue
                rank += 1
                if rank > 50:
                    break
                title = item.get("word", "").strip()
                if not title:
                    continue
                hot_score = item.get("hotScore", "0")
                try:
                    hot_val = int(str(hot_score).replace(",", "").replace("_", ""))
                except (ValueError, TypeError):
                    hot_val = 0

                # 趋势标签
                hot_tag = item.get("hotTag", "0")
                new_hot_name = item.get("newHotName", "")
                label_tag_name = item.get("labelTagName", "")
                trend = "stable"
                if new_hot_name in ("热", "爆"):
                    trend = "up"
                elif new_hot_name == "新":
                    trend = "new"
                elif label_tag_name:
                    trend = "up"

                results.append(
                    {
                        "title": title,
                        "rank": rank,
                        "url": item.get("rawUrl", item.get("url", f"https://www.baidu.com/s?wd={title}")),
                        "hot_value": hot_val,
                        "hot_value_raw": str(hot_score),
                        "trend": trend,
                        "cover_url": item.get("img", ""),
                        "extra": {
                            "desc": item.get("desc", ""),
                            "label": new_hot_name or label_tag_name,
                        },
                    }
                )
            if rank > 50:
                break

        logger.info("baidu trending: fetched %d items", len(results))
        return results
