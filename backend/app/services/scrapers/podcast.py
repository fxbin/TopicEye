"""
Podcast scraper.

Almost every podcast platform is, underneath, an RSS feed with ``<enclosure>``
audio URLs. This scraper resolves the source URL to that RSS feed (via
Apple iTunes lookup, page-meta extraction, or direct use) and then reuses
the RSS feedparser pipeline.

Supported inputs:
    - podcasts.apple.com/<lang>/podcast/<slug>/id<id>  → iTunes lookup
    - xiaoyuzhoufm.com/podcast/<id>                    → page <link rel="alternate">
    - *.buzzsprout.com, *.podbean.com, anchor.fm/<show> → assume URL is the feed
    - open.spotify.com/show/<id>                       → best-effort (Spotify has no
                                                            public feed; rely on a
                                                            third-party bridge URL if
                                                            user pastes one)
    - any *.xml / *.rss URL                            → used directly
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from . import BaseScraper, fetch_feed_with_retry, register_scraper

logger = logging.getLogger(__name__)


@register_scraper("Podcast")
class PodcastScraper(BaseScraper):
    """Podcast source backed by an RSS feed."""

    def __init__(self, source_url: str, source_config=None):
        super().__init__(source_url, source_config)
        # source_config may carry a pre-resolved feedUrl (e.g. from recognizer)
        self.rss_url: str | None = source_config.get("resolved_rss_url") if source_config else None
        self.itunes_id: str | None = source_config.get("itunes_id") if source_config else None

    async def _resolve_rss_url(self, client: httpx.AsyncClient) -> str:
        """Map a podcast landing URL to its underlying RSS feed URL."""
        parsed = urlparse(self.url)
        host = (parsed.hostname or "").lower()
        path = parsed.path or "/"

        # Already an RSS feed URL — use directly
        if path.endswith((".xml", ".rss", ".atom")) or "/rss" in path:
            return self.url

        # Apple Podcast / iTunes → use the public lookup API to get feedUrl
        if host in {"podcasts.apple.com", "itunes.apple.com"}:
            itunes_id = self.itunes_id
            if not itunes_id:
                m = re.search(r"/id(\d+)", path)
                itunes_id = m.group(1) if m else None
            if itunes_id:
                lookup_url = f"https://itunes.apple.com/lookup?id={itunes_id}&entity=podcast"
                try:
                    resp = await client.get(lookup_url)
                    resp.raise_for_status()
                    data = resp.json()
                    results = data.get("results") or []
                    if results:
                        feed_url = results[0].get("feedUrl")
                        if feed_url:
                            return feed_url
                except Exception as exc:  # noqa: BLE001
                    logger.warning("iTunes lookup failed for %s: %s", self.url, exc)

        # xiaoyuzhoufm — best-effort: try the RSS bridge pattern, fall back to URL
        if host == "xiaoyuzhoufm.com" or host.endswith(".xiaoyuzhoufm.com"):
            # xiaoyuzhoufm exposes /podcast/<id>; their RSS bridge is at
            # feeds.xiaoyuzhoufm.com/<id> — but the format is not officially
            # documented. Fall back to fetching the page and looking for
            # <link rel="alternate" type="application/rss+xml">.
            return await self._extract_rss_from_html(client, self.url) or self.url

        # Generic — try to extract <link rel="alternate" type="application/rss+xml">
        rss = await self._extract_rss_from_html(client, self.url)
        if rss:
            return rss

        # Last-resort: assume the URL itself is the feed
        return self.url

    @staticmethod
    async def _extract_rss_from_html(client: httpx.AsyncClient, url: str) -> str | None:
        """Best-effort: fetch ``url`` as HTML and look for an RSS <link>."""
        try:
            resp = await client.get(url, follow_redirects=True)
            resp.raise_for_status()
            html = resp.text
            # Common patterns in podcast landing pages
            patterns = [
                r'<link[^>]+type=["\']application/rss\+xml["\'][^>]+href=["\']([^"\']+)',
                r'<link[^>]+href=["\']([^"\']+\.rss)["\']',
                r'<link[^>]+href=["\']([^"\']+\.xml)["\']',
            ]
            for pattern in patterns:
                m = re.search(pattern, html, re.IGNORECASE)
                if m:
                    return m.group(1)
        except Exception as exc:  # noqa: BLE001
            logger.debug("RSS extraction from %s failed: %s", url, exc)
        return None

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        if not self.rss_url:
            self.rss_url = await self._resolve_rss_url(client)

        resp = await fetch_feed_with_retry(
            client,
            self.rss_url,
            context=f"Podcast {self.rss_url}",
        )
        if resp is None:
            logger.warning("Podcast feed exhausted retries, returning empty: %s", self.rss_url)
            return []
        if resp.status_code == 304:
            logger.info("Podcast feed not modified: %s", self.rss_url)
            return []

        feed = feedparser.parse(resp.text)
        entries: list[dict[str, Any]] = []

        for entry in feed.entries:
            published = entry.get("published_parsed") or entry.get("updated_parsed")
            published_at = datetime(*published[:6]) if published else datetime.now(UTC)
            # Podcast cover art: itunes:image or enclosure
            cover_url = ""
            if "itunes_image" in entry:
                cover_url = entry.itunes_image.get("href", "")
            elif "image" in entry and hasattr(entry.image, "get"):
                cover_url = entry.image.get("href", "")

            entries.append(
                {
                    "title": entry.get("title", ""),
                    "url": entry.get("link", ""),
                    "author": entry.get("author", ""),
                    "summary": entry.get("summary", ""),
                    "raw_content": (entry.get("content", [{}])[0].get("value", "") if entry.get("content") else ""),
                    "tags": [tag.get("term", "") for tag in entry.get("tags", [])],
                    "published_at": published_at,
                    "cover_url": cover_url,
                }
            )

        return entries
