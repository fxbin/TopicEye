"""中文播客榜 (xyzrank) — https://xyzrank.com/

源: xyzrank 中文播客榜公开 JSON API (Express + Cloudflare, 5min 缓存).
数据取自小宇宙和 Apple Podcast, 非全平台, 每日更新.
- 接口: GET https://xyzrank.com/api/episodes?offset=0&limit=50
- 鉴权: 无
- 字段: title / podcastName / playCount / commentCount / link / logoURL /
        primaryGenreName / duration / postTime / rank / subscription / openRate
- 失败模式:
    * 网络错误 / 非 200: 返回空列表, 记 warning
    * 字段缺失: 单条跳过, 不影响整批
    * Cloudflare 偶发挑战: pipeline 层有 retry, 这里 fail-fast
"""

from __future__ import annotations

import logging

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry, BROWSER_UA

logger = logging.getLogger(__name__)

API_URL = "https://xyzrank.com/api/episodes"
HEADERS = {
    "User-Agent": BROWSER_UA,
    "Referer": "https://xyzrank.com/",
    "Accept": "application/json, text/plain, */*",
}
DEFAULT_LIMIT = 50


def _fmt_play(count: int) -> str:
    """播放量转中文短文本: 319377 -> '31.9万播放'."""
    if count >= 10000:
        return f"{count / 10000:.1f}万播放"
    return f"{count}播放"


@register_trending("xyzrank")
class XyzrankTrending(BaseTrendingScraper):
    SOURCE = "xyzrank"
    CATEGORY = "podcast"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        try:
            resp = await client.get(
                API_URL,
                params={"offset": 0, "limit": DEFAULT_LIMIT},
                headers=HEADERS,
            )
            resp.raise_for_status()
            payload = resp.json()
        except Exception as e:
            logger.warning("xyzrank trending fetch failed: %s", e)
            return []

        items = payload.get("items") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            logger.warning("xyzrank: unexpected payload shape (no items list)")
            return []

        results: list[TrendingEntry] = []
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = (raw.get("title") or "").strip()
            if not title:
                continue

            podcast_name = (raw.get("podcastName") or "").strip()
            # 播客名是关键归属信息, 拼进标题避免前端只看到 episode 名
            full_title = f"{title} | {podcast_name}" if podcast_name else title

            play_count = int(raw.get("playCount") or 0)
            comment_count = int(raw.get("commentCount") or 0)
            duration_min = int(raw.get("duration") or 0)

            results.append(
                {
                    "title": full_title,
                    "rank": int(raw.get("rank") or len(results) + 1),
                    "url": (raw.get("link") or "").strip(),
                    "hot_value": play_count,
                    "hot_value_raw": _fmt_play(play_count),
                    "trend": "stable",
                    "cover_url": (raw.get("logoURL") or "").strip() or None,
                    "extra": {
                        "podcast_name": podcast_name,
                        "comment_count": comment_count,
                        "duration_min": duration_min,
                        "genre": (raw.get("primaryGenreName") or "").strip(),
                        "post_time": raw.get("postTime") or "",
                        "subscription": int(raw.get("subscription") or 0),
                    },
                }
            )

        logger.info("xyzrank trending: fetched %d episodes", len(results))
        return results
