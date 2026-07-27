"""网易新闻热点 — https://m.163.com/nc/article/headline/T1348647853363/0-40.html"""

from __future__ import annotations

import logging

import httpx

from . import BaseTrendingScraper, TrendingEntry, register_trending

logger = logging.getLogger(__name__)


@register_trending("netease")
class NeteaseTrending(BaseTrendingScraper):
    SOURCE = "netease"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        url = "https://m.163.com/nc/article/headline/T1348647853363/0-40.html"
        headers = self._build_headers(
            Referer="https://m.163.com/",
            Accept="application/json",
        )
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
            return []

        # 响应结构: { "T1348647853363": [ ...articles ] }
        articles = data.get("T1348647853363", [])
        if not articles:
            logger.warning("netease trending: no articles found")
            return []

        results: list[TrendingEntry] = []
        for rank, item in enumerate(articles, start=1):
            if not isinstance(item, dict):
                continue
            title = item.get("title", "").strip()
            if not title:
                continue

            # 文章 ID 作为唯一标识
            article_id = item.get("docid", item.get("postid", ""))

            # replyCount 转 hot_value
            reply_count = item.get("replyCount", 0)
            try:
                hot_val = int(reply_count)
            except (ValueError, TypeError):
                hot_val = 0

            # 文章链接
            article_url = item.get("url", item.get("url_3w", ""))

            results.append(
                {
                    "title": title,
                    "rank": rank,
                    "url": article_url,
                    "hot_value": hot_val,
                    "hot_value_raw": str(reply_count),
                    "trend": "stable",
                    "cover_url": item.get("imgsrc", ""),
                    "extra": {
                        "article_id": article_id,
                        "source": item.get("source", ""),
                        "digest": item.get("digest", ""),
                    },
                }
            )

        logger.info("netease trending: fetched %d items", len(results))
        return results
