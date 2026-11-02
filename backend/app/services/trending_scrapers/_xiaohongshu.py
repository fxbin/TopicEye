"""小红书热榜 — 60s 聚合 API 代理（/v2/rednote）

小红书 App 接口反爬严，直连需伪造设备指纹头（属绕反爬，不做），故经
开源聚合服务 60s API 的代理通道取数；实例地址经 settings.API60S_BASE_URL
可替换（自部署/社区实例）。上游返回 5xx 或异常数据时降级为空列表，
不影响其他信源同步（pipeline 对空结果不删旧数据）。
"""

from __future__ import annotations

import logging
import re

import httpx

from app.core.config import settings

from . import BaseTrendingScraper, TrendingEntry, register_trending, truncate_title

logger = logging.getLogger(__name__)

# score 可能是数字或 "1234万" 这类文本
_HOT_VALUE_RE = re.compile(r"^([\d.]+)\s*(万)?")


def _parse_hot_value(raw: object) -> int:
    """score 容错解析：数字/数字字符串/"N万" → int；无法解析返回 0。"""
    if isinstance(raw, bool):  # bool 是 int 子类，先排除
        return 0
    if isinstance(raw, int | float):
        return int(raw)
    if isinstance(raw, str):
        m = _HOT_VALUE_RE.match(raw.strip())
        if m:
            val = float(m.group(1))
            if m.group(2):
                val *= 10000
            return int(val)
    return 0


@register_trending("xiaohongshu")
class XiaohongshuTrending(BaseTrendingScraper):
    SOURCE = "xiaohongshu"
    CATEGORY = "hot"

    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        base = settings.API60S_BASE_URL.rstrip("/")
        url = f"{base}/v2/rednote"
        headers = self._build_headers(Accept="application/json")
        data = await self._fetch_json(client, url, headers=headers)
        if data is None:
            return []

        if data.get("code") != 200:
            logger.warning("xiaohongshu trending: api code=%s", data.get("code"))
            return []
        items = data.get("data") or []
        if not items:
            logger.warning("xiaohongshu trending: empty data")
            return []

        results: list[TrendingEntry] = []
        for idx, item in enumerate(items, start=1):
            title = str(item.get("title") or "").strip()
            if not title:
                continue

            score_raw = item.get("score")
            results.append(
                {
                    "title": truncate_title(title),
                    "rank": int(item.get("rank") or idx),
                    "url": str(item.get("link") or ""),
                    "hot_value": _parse_hot_value(score_raw),
                    "hot_value_raw": str(score_raw if score_raw is not None else ""),
                    "trend": "stable",
                    "cover_url": str(item.get("work_type_icon") or ""),
                    "extra": {
                        "word_type": str(item.get("word_type") or ""),
                    },
                }
            )

        logger.info("xiaohongshu trending: fetched %d items", len(results))
        return results
