"""
YouTube scraper.

Uses YouTube's official per-channel RSS feed:
    https://www.youtube.com/feeds/videos.xml?channel_id=<UC...>

The RSS feed returns the latest ~15 videos as an Atom feed (parsed by
feedparser). To get the ``channel_id`` from a user-supplied URL, three
shapes are supported:

    - youtube.com/channel/<UCxxxx>           → extract directly
    - youtube.com/feeds/videos.xml?channel_id= → extract from query
    - youtube.com/@<handle> / /user/<name>    → fetch HTML page and parse
                                                 <meta itemprop="channelId">
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone, UTC
from typing import Any, Optional
from urllib.parse import urlparse

import feedparser
import httpx

from . import BaseScraper, register_scraper, fetch_feed_with_retry

logger = logging.getLogger(__name__)

YOUTUBE_FEED_TEMPLATE = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"


@register_scraper("YouTube")
class YouTubeScraper(BaseScraper):
    """YouTube channel scraper backed by the official Atom RSS feed."""

    def __init__(self, source_url: str, source_config=None):
        super().__init__(source_url, source_config)
        self.channel_id: str | None = source_config.get("channel_id") if source_config else None
        self._rss_url: str | None = None

    @staticmethod
    def _extract_channel_id_from_url(url: str) -> str | None:
        """Best-effort channel_id extraction without network access."""
        if not url:
            return None
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        query = parsed.query or ""

        if host not in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
            return None

        # /channel/UCxxxx
        m = re.match(r"^/channel/([A-Za-z0-9_-]+)", path)
        if m:
            return m.group(1)

        # ?channel_id=UCxxxx
        m = re.search(r"channel_id=([A-Za-z0-9_-]+)", query)
        if m:
            return m.group(1)

        return None

    async def _resolve_channel_id(self, client: httpx.AsyncClient) -> str | None:
        """Resolve a /@handle or /user/<name> URL to a UC channel_id."""
        # First try the URL itself
        direct = self._extract_channel_id_from_url(self.url)
        if direct:
            return direct

        # Fetch the page HTML and look for <meta itemprop="channelId" content="UC...">
        try:
            resp = await client.get(self.url, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
            patterns = [
                r'<meta[^>]+itemprop=["\']channelId["\'][^>]+content=["\']([UCa-zA-Z0-9_-]+)',
                r'"channelId"\s*:\s*"([UCa-zA-Z0-9_-]+)"',
                r'<link[^>]+rel=["\']canonical["\'][^>]+href=["\']https?://www\.youtube\.com/channel/([UCa-zA-Z0-9_-]+)',
            ]
            for pattern in patterns:
                m = re.search(pattern, html)
                if m:
                    return m.group(1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("YouTube channel_id resolution failed for %s: %s", self.url, exc)
        return None

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if not self.channel_id:
            self.channel_id = await self._resolve_channel_id(client)
        if not self.channel_id:
            logger.warning("YouTube scraper could not resolve channel_id for %s", self.url)
            return []

        self._rss_url = YOUTUBE_FEED_TEMPLATE.format(channel_id=self.channel_id)
        resp = await fetch_feed_with_retry(
            client, self._rss_url, context=f"YouTube {self._rss_url}",
        )
        if resp is None:
            logger.warning("YouTube feed exhausted retries, returning empty: %s", self._rss_url)
            return []
        if resp.status_code == 304:
            logger.info("YouTube feed not modified: %s", self._rss_url)
            return []

        feed = feedparser.parse(resp.text)
        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_at = datetime(*published[:6]) if published else datetime.now(UTC)
            # Atom feed uses <author><name>; feedparser surfaces as entry.author
            author = entry.get("author", "")
            # cover_url from media:thumbnail / media:group
            cover_url = ""
            if "media_thumbnail" in entry:
                thumb = entry.media_thumbnail
                if isinstance(thumb, list) and thumb:
                    cover_url = thumb[0].get("url", "")
                elif hasattr(thumb, "get"):
                    cover_url = thumb.get("url", "")
            elif "media_content" in entry:
                mc = entry.media_content
                if isinstance(mc, list) and mc and "url" in mc[0]:
                    cover_url = mc[0].get("url", "")

            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "author": author,
                    "summary": entry.get("summary", ""),
                    "raw_content": (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""),
                    "tags": [tag.get("term", "") for tag in entry.get("tags", [])],
                    "published_at": published_at,
                    "cover_url": cover_url,
                }
            )

        return entries
