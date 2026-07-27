"""
知乎热榜爬虫 — 使用知乎官方热榜 API.

Uses curl subprocess to bypass potential TLS fingerprinting,
similar to the Reddit scraper pattern.

API: https://api.zhihu.com/topstory/hot-list?limit=50
Returns JSON with hot list topics.

source_url: 不需要（知乎热榜是固定的）
source_config (JSON via Source.source_config):
    fetch_limit:    int  1-50  (default 50)
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from app.services.zhihu_url import normalize_zhihu_url

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)

ZHIHU_HOT_API = "https://api.zhihu.com/topstory/hot-list"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)


# ── curl-based HTTP helper ──────────────────────────────────────────


async def _curl_get(url: str, params: dict[str, Any] | None = None) -> Any | None:
    """Run curl subprocess to fetch JSON from Zhihu, bypassing TLS fingerprinting."""
    full_url = f"{url}?{urlencode(params)}" if params else url

    cmd = [
        "curl",
        "-sS",
        "--max-time",
        "20",
        "-H",
        f"User-Agent: {USER_AGENT}",
        "-H",
        "Accept: application/json,text/plain,*/*",
        "-H",
        "Accept-Language: zh-CN,zh;q=0.9,en-US;q=0.8",
        "-H",
        "Referer: https://www.zhihu.com/hot",
    ]

    # Add proxy if available
    import os

    proxy = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
    if proxy:
        cmd.extend(["--proxy", proxy])

    cmd.append(full_url)

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=25)

        if proc.returncode != 0:
            err_msg = stderr.decode(errors="replace")[:200]
            logger.warning("curl failed (rc=%d) for %s: %s", proc.returncode, full_url, err_msg)
            return None

        text = stdout.decode(errors="replace")
        if not text:
            return None

        # Detect HTML error pages
        text_stripped = text.strip()
        if text_stripped.startswith("<!"):
            logger.warning("Zhihu returned HTML instead of JSON for %s", full_url)
            return None

        return json.loads(text)

    except TimeoutError:
        logger.warning("curl timeout for %s", full_url)
        return None
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON from %s: %s", full_url, e)
        return None
    except Exception as e:
        logger.warning("curl error for %s: %s", full_url, e)
        return None


def _extract_hot_score(detail_text: str) -> int:
    """Extract numeric hot score from Zhihu detail_text like '2345 万热度'."""
    if not detail_text:
        return 0
    # Match patterns like "1234 万热度", "12345 热度", or "1_2345678.123 万热度" (underscore-separated float)
    match = re.search(r"([\d_.,]+)\s*万?热度", detail_text)
    if match:
        num_str = match.group(1).replace(",", "").replace("_", "")
        try:
            num = float(num_str)
        except ValueError:
            return 0
        # If "万热度", multiply by 10000
        if "万热度" in detail_text:
            num *= 10000
        return int(num)
    # Fallback: try to extract any number
    match = re.search(r"([\d_.,]+)", detail_text)
    if match:
        try:
            return int(float(match.group(1).replace(",", "").replace("_", "")))
        except ValueError:
            return 0
    return 0


@register_scraper("ZHIHU")
class ZhihuScraper(BaseScraper):
    """
    Fetch hot list topics from Zhihu via the public hot-list API
    using curl to bypass potential TLS fingerprinting.
    """

    def __init__(self, source_url: str, source_config: dict | None = None):
        super().__init__(source_url, source_config or {})
        # source_url is not used for Zhihu (hot list is fixed)
        self.fetch_limit = min(self.config.get("fetch_limit", 50), 50)

    # ── Public entry ────────────────────────────────────────────────

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch Zhihu hot list and return normalised entry dicts.

        NOTE: The ``client`` parameter is accepted for BaseScraper interface
        compatibility but is NOT used — all HTTP calls go through curl subprocess.
        """
        params: dict[str, Any] = {"limit": self.fetch_limit}
        data = await _curl_get(ZHIHU_HOT_API, params)
        if not data:
            return []

        items = data.get("data", [])
        if not items:
            logger.warning("Zhihu hot list returned empty data")
            return []

        entries: list[dict[str, Any]] = []
        for item in items:
            entry = self._parse_item(item)
            if entry:
                entries.append(entry)

        logger.info(
            "Zhihu hot list: fetched %d topics",
            len(entries),
        )
        return entries

    # ── Parse ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_item(item: dict) -> dict[str, Any] | None:
        target = item.get("target", {})
        if not target:
            return None

        title = target.get("title", "")
        url = normalize_zhihu_url(target.get("url", ""))
        excerpt = target.get("excerpt", "")
        detail_text = item.get("detail_text", "")

        # Author
        author = ""
        author_info = target.get("author")
        if author_info and isinstance(author_info, dict):
            author = author_info.get("name", "")

        # Hot score from detail_text — ensure int
        hot_score = _extract_hot_score(detail_text)

        # Thumbnail / cover
        thumbnail = target.get("thumbnail") or target.get("image_url")

        # Tags from topic
        tags: list[str] = []
        # Zhihu sometimes includes type in the item
        item_type = item.get("type", "")
        if item_type and "advert" in item_type:
            return None

        # Build summary
        summary = excerpt if excerpt else title
        if len(summary) > 300:
            summary = summary[:297] + "..."

        # Build raw_content with hot score info
        parts: list[str] = []
        if excerpt:
            parts.append(excerpt)
        if detail_text:
            parts.append(f"[热度: {detail_text}]")
        raw_content = "\n\n".join(parts)

        return {
            "title": title,
            "url": url,
            "author": author,
            "summary": summary,
            "raw_content": raw_content if raw_content else None,
            "tags": tags,
            "published_at": datetime.now(UTC),
            "cover_url": thumbnail,
            # Zhihu-specific metadata stored for scoring engine
            "_zhihu_meta": {
                "hot_score": hot_score,
                "detail_text": detail_text,
                "rank": item.get("id", 0),
                "excerpt": excerpt,
            },
        }
