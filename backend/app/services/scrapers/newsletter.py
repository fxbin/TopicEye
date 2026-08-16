"""
Newsletter scraper.

Most newsletter platforms (Substack, beehiiv, Buttondown, Tinyletter, ...)
publish a built-in RSS feed at a well-known path. This scraper normalises
the user-provided URL to that RSS feed URL and reuses the RSS feedparser
pipeline.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from . import BaseScraper, fetch_feed_with_retry, register_scraper

logger = logging.getLogger(__name__)


@register_scraper("Newsletter")
class NewsletterScraper(BaseScraper):
    """Newsletter source backed by a platform's built-in RSS feed.

    Supports Substack, beehiiv, Buttondown, Tinyletter out of the box. For
    any URL that is already an RSS feed (e.g. kill-the-newsletter bridges)
    it falls through to plain feedparser.
    """

    def __init__(self, source_url: str, source_config=None):
        super().__init__(source_url, source_config)
        self.rss_url = self._normalize_to_rss(source_url)

    @staticmethod
    def _normalize_to_rss(url: str) -> str:
        """Map a newsletter landing URL to its built-in RSS feed URL."""
        if not url:
            return url
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"

        # Strip trailing slash for normalisation
        base = f"{parsed.scheme}://{parsed.netloc}"

        # Substack: https://xxx.substack.com → https://xxx.substack.com/feed
        if host.endswith(".substack.com"):
            return f"{base}/feed"
        # Beehiiv: https://xxx.beehiiv.com → https://xxx.beehiiv.com/feed
        if host.endswith(".beehiiv.com"):
            return f"{base}/feed"
        # Buttondown: https://buttondown.email/<name> → /<name>/rss
        if host == "buttondown.email":
            seg = path.strip("/").split("/", 1)[0]
            if seg and seg.lower() not in {"login", "signup", "about"}:
                return f"{base}/{seg}/rss"
            return f"{base}/rss"
        # Tinyletter: https://tinyletter.com/<name> → /<name>?format=rss
        if host == "tinyletter.com" or host.endswith(".tinyletter.com"):
            seg = path.strip("/").split("/", 1)[0]
            if seg:
                return f"{base}/{seg}?format=rss"
            return url
        # Already an RSS URL — keep as-is
        return url

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        resp = await fetch_feed_with_retry(
            client,
            self.rss_url,
            context=f"Newsletter {self.rss_url}",
        )
        if resp is None:
            logger.warning("Newsletter feed exhausted retries, returning empty: %s", self.rss_url)
            return []
        if resp.status_code == 304:
            logger.info("Newsletter feed not modified: %s", self.rss_url)
            return []

        feed = feedparser.parse(resp.text)
        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_at = datetime(*published[:6]) if published else datetime.now(UTC)
            cover_url = ""
            # Substack: image inside summary HTML — best-effort extract <img src>.
            summary = entry.get("summary", "")
            if "<img" in summary:
                import re

                img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', summary)
                if img_match:
                    cover_url = img_match.group(1)

            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "author": entry.get("author", ""),
                    "summary": summary,
                    "raw_content": (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""),
                    "tags": [tag.get("term", "") for tag in entry.get("tags", [])],
                    "published_at": published_at,
                    "cover_url": cover_url,
                }
            )

        return entries
