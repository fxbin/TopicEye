"""
RSS / Atom feed scraper.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, UTC
from typing import Any

import feedparser
import httpx

from . import BaseScraper, register_scraper, fetch_feed_with_retry

logger = logging.getLogger(__name__)

# arXiv RSS 的 <description> 带 'arXiv:XXXX.NNNNN Announce Type: new\nAbstract: '
# 固定前缀，并非真正的摘要。清理掉让 LLM 拿到干净摘要。
# 很多 RSS 源的 description 都带类似模板前缀，这是通用清理，不只服务 arXiv。
_ARXIV_PREFIX_RE = re.compile(
    r"^arXiv:\S+\s+Announce Type:\s*\S+\s*\n?Abstract:\s*", re.IGNORECASE
)


def _clean_summary(text: str) -> str:
    """清理 RSS summary 中的模板前缀（如 arXiv 的 announce 行）。"""
    if not text:
        return text
    return _ARXIV_PREFIX_RE.sub("", text, count=1).strip()


@register_scraper("RSS")
class RSSScraper(BaseScraper):
    """Fetch and parse RSS/Atom feeds."""

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        resp = await fetch_feed_with_retry(
            client, self.url, context=f"RSS {self.url}",
        )
        if resp is None:
            logger.warning("RSS feed exhausted retries, returning empty: %s", self.url)
            return []
        # Capture conditional request state so the pipeline can persist it on
        # the Source row and send If-None-Match / If-Modified-Since next time.
        self._latest_etag = resp.headers.get("etag")
        self._latest_last_modified = resp.headers.get("last-modified")

        if resp.status_code == 304:
            logger.info("RSS feed not modified: %s", self.url)
            return []

        feed = feedparser.parse(resp.text)
        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_at = datetime(*published[:6]) if published else datetime.now(UTC)

            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "author": entry.get("author", ""),
                    "summary": _clean_summary(entry.get("summary", "")),
                    "raw_content": (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""),
                    "tags": [tag.get("term", "") for tag in entry.get("tags", [])],
                    "published_at": published_at,
                }
            )

        return entries
