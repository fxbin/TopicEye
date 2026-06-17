"""
抖音热榜 scraper — https://so-landing.douyin.com/landings/hotlist
数据来自 /aweme/v1/web/hot/search/list/ 接口，无需登录。

source_url: 固定填 https://so-landing.douyin.com/landings/hotlist（实际抓取用API）
source_config (JSON via Source.source_config):
    fetch_limit:    int  最多取多少条 (default 50)
    tab_type:       str  榜单类型 (hot/default/... 默认 hot)
"""

from __future__ import annotations

import logging
import re
from typing import Optional, Any

import httpx

from . import BaseScraper, register_scraper

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
    """Parse hot_value from API — string like '1110万' or '837.3万'."""
    if not raw:
        return 0
    s = str(raw).strip().replace(",", "").replace("_", "")
    try:
        val = float(s)
        if val < 10000:  # "万"为单位，转为整数
            val = val * 10000
        return int(val)
    except (ValueError, TypeError):
        return 0


@register_scraper("DouyinHot")
class DouyinHotScraper(BaseScraper):
    """抖音热榜 — 热点榜/种草榜/娱乐榜/社会榜/北京榜"""

    def __init__(self, source_url: str, source_config: Optional[dict] = None):
        super().__init__(source_url, source_config or {})
        self.fetch_limit: int = self.config.get("fetch_limit", 50)

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """
        Fetch hot list from Douyin public API.
        client is provided by the pipeline (shared httpx session).
        """
        try:
            resp = await client.get(HOT_LIST_URL, headers=_HEADERS)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.warning("douyin hot fetch failed: %s", e)
            return []

        word_list: list = data.get("data", {}).get("word_list", [])
        if not word_list:
            logger.warning("douyin hot: word_list empty, status=%s", data.get("status_code"))
            return []

        results = []
        for idx, item in enumerate(word_list[: self.fetch_limit], start=1):
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
                    "url": jump_url,
                    "author": "抖音热榜",
                    "summary": sentence.get("title", "") or word,
                    "raw_content": "",
                    "tags": [],
                    "published_at": None,
                    "cover_url": None,
                    "hot_score": hot_score,
                    "hot_score_raw": str(hot_value_raw),
                    "rank": idx,
                    "rank_score": max(0, 100 - (idx - 1) * 2),
                    "category_tags": ",".join(labels) if labels else "",
                    "_douyin_hot_meta": {
                        "hot_score": hot_score,
                        "rank": idx,
                        "word_id": item.get("id", ""),
                        "sentence_title": sentence.get("title", ""),
                        "event_time": item.get("event_time", ""),
                    },
                }
            )

        logger.info("douyin hot: fetched %d items", len(results))
        return results
