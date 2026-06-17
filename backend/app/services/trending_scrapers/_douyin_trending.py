"""抖音热榜（趋势雷达版）— 复用 douyin_hot 的 API"""

from __future__ import annotations

import logging
from typing import Any, List

import httpx
from . import BaseTrendingScraper, register_trending, TrendingEntry

logger = logging.getLogger(__name__)

HOT_LIST_URL = (
    "https://www.douyin.com/aweme/v1/web/hot/search/list/"
    "?device_platform=webapp&aid=6383&channel=channel_pc_web"
    "&detail_list=1&update_version_code=170400&version_code=170400"
    "&version_name=17.4.0&cookie_enabled=true&screen_width=1920"
    "&screen_height=1080&browser_language=zh-CN&browser_platform=Win32"
    "&browser_name=Chrome&browser_version=131.0.0.0&browser_online=true"
    "&engine_name=Blink&engine_version=131.0.0.0&os_name=Windows&os_version=10"
    "&cpu=Intel&device_memory=8&platform=PC&downlink=10&effective_type=4g&round_trip_time=50"
)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Referer": "https://so-landing.douyin.com/landings/hotlist",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "application/json, text/plain, */*",
}


def _parse_hot_value(raw: Any) -> int:
    if not raw:
        return 0
    s = str(raw).strip().replace(",", "").replace("_", "")
    try:
        val = float(s)
        return int(val)
    except (ValueError, TypeError):
        return 0


@register_trending("douyin")
class DouyinTrending(BaseTrendingScraper):
    SOURCE = "douyin"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        try:
            resp = await client.get(HOT_LIST_URL, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("douyin trending fetch failed: %s", e)
            return []

        word_list = data.get("data", {}).get("word_list", [])
        if not word_list:
            logger.warning("douyin trending: word_list empty")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(word_list[:50], start=1):
            word = item.get("word", "").strip()
            if not word:
                continue

            hot_value_raw = item.get("hot_value", item.get("value", ""))
            hot_score = _parse_hot_value(hot_value_raw)
            sentence: dict = item.get("sentence", {}) or {}
            jump_url = sentence.get("url", "") or f"https://www.douyin.com/search/{word}"

            raw_labels = item.get("label")
            labels = []
            if isinstance(raw_labels, list):
                labels = [l.get("name", "") for l in raw_labels if isinstance(l, dict) and l.get("name")]

            results.append(
                {
                    "title": word,
                    "rank": idx,
                    "url": jump_url,
                    "hot_value": hot_score,
                    "hot_value_raw": str(hot_value_raw),
                    "trend": "up" if idx <= 5 else "stable",
                    "extra": {
                        "sentence_title": sentence.get("title", ""),
                        "labels": labels,
                    },
                }
            )

        logger.info("douyin trending: fetched %d items", len(results))
        return results
