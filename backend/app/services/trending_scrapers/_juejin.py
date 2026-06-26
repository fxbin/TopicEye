"""掘金热榜 — https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"""

from __future__ import annotations

import logging
from typing import List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, truncate_title

logger = logging.getLogger(__name__)


@register_trending("juejin")
class JuejinTrending(BaseTrendingScraper):
    SOURCE = "juejin"
    CATEGORY = "tech"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://api.juejin.cn/recommend_api/v1/article/recommend_all_feed"
        payload = {
            "id_type": 2,
            "client_type": 2608,
            "sort_type": 200,  # 热门排序
            "cursor": "0",
            "limit": 30,
        }
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://juejin.cn/",
            "Content-Type": "application/json",
        }
        try:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("juejin trending fetch failed: %s", e)
            return []

        raw_items = data.get("data", [])
        if not raw_items:
            logger.warning("juejin trending: empty data")
            return []

        results: list[TrendingEntry] = []
        for idx, raw in enumerate(raw_items[:30], start=1):
            # 数据在 item_info.article_info 里
            item_info = raw.get("item_info", {})
            article = item_info.get("article_info", {})
            if not article:
                continue
            title = article.get("title", "").strip()
            if not title:
                continue

            article_id = article.get("article_id", "")
            digg = article.get("digg_count", 0)
            view = article.get("view_count", 0)
            comment = article.get("comment_count", 0)
            hot_index = article.get("hot_index", 0)

            author_info = item_info.get("author_user_info", {})
            author = author_info.get("user_name", "")

            results.append(
                {
                    "title": truncate_title(title),
                    "rank": idx,
                    "url": f"https://juejin.cn/post/{article_id}",
                    "hot_value": hot_index or (digg * 100 + view + comment * 50),
                    "hot_value_raw": f"赞{digg} 读{view} 评{comment}",
                    "trend": "up" if idx <= 5 else "stable",
                    "extra": {
                        "author": author,
                        "digg_count": digg,
                        "view_count": view,
                        "comment_count": comment,
                    },
                }
            )

        logger.info("juejin trending: fetched %d items", len(results))
        return results
