"""
Twitter RSS scraper via xgo.ing RSS feeds.

Fetches tweets from xgo.ing's RSS feed service, which provides
Twitter/X user timelines as standard RSS/Atom feeds.

source_url: Full RSS URL from xgo.ing, e.g.
    "https://xgo.ing/elonmusk/rss"
    "https://xgo.ing/{username}/rss"
source_config (JSON via Source.source_config):
    api_key: str          — xgo.ing API key (optional, can also use XGO_API_KEY env var)
    fetch_limit: int      — max entries to return (default 50)
    include_retweets: bool — include retweets (default False)
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, Optional

import feedparser
import httpx

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)


def _extract_username(url: str) -> str:
    """Extract Twitter username from xgo.ing URL.

    Supports both URL formats:
    - https://api.xgo.ing/rss/user/{hash}  (BestBlogs OPML format)
    - https://xgo.ing/{username}/rss        (direct format)
    """
    # Direct format: https://xgo.ing/username/rss
    match = re.match(r"https?://(?:www\.)?xgo\.ing/([^/?#\s]+)(?:/rss)?", url)
    if match:
        return match.group(1).strip().lstrip("@")
    return ""


def _clean_tweet_text(text: str) -> str:
    """Clean HTML, engagement metrics footer, and excess whitespace from tweet text."""
    if not text:
        return ""
    # Replace <br> with newlines first
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    # Unescape HTML entities
    text = unescape(text)
    # Remove engagement metrics footer: 💬12 🔄8 ❤️116 👀37383 📊23
    text = re.sub(r"[\U0001F4AC\U0001F504\U00002764\U0001F493\U0001F440\U0001F4CA\u2764\u2605]\uFE0F?\d+", "", text)
    # Remove "⚡ Powered by xgo.ing" footer
    text = re.sub(r"⚡\s*Powered by xgo\.ing", "", text)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    return text.rstrip()


@register_scraper("TWITTER_RSS")
@register_scraper("TwitterRSS")
class TwitterRSSScraper(BaseScraper):
    """
    Fetch tweets via xgo.ing RSS feeds.

    Uses feedparser to parse the standard RSS/Atom output from xgo.ing.
    Supports optional API key authentication via source_config or env var.
    """

    def __init__(self, source_url: str, source_config: Optional[dict] = None):
        super().__init__(source_url, source_config or {})
        self.api_key = self.config.get("api_key") or os.environ.get("XGO_API_KEY", "")
        self.fetch_limit = min(self.config.get("fetch_limit", 50), 100)
        self.include_retweets = self.config.get("include_retweets", False)
        self.username = _extract_username(source_url) or self.config.get("screen_name", "")

        # Ensure URL ends with /rss
        if self.url and not self.url.rstrip("/").endswith("/rss"):
            self.url = self.url.rstrip("/") + "/rss"

    # ── Public entry ────────────────────────────────────────────────

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Fetch tweets from xgo.ing RSS and return normalised entry dicts."""
        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = await client.get(self.url, headers=headers, timeout=20.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "TwitterRSSScraper: HTTP %d for %s: %s",
                exc.response.status_code,
                self.url,
                exc,
            )
            return []
        except httpx.HTTPError as exc:
            logger.warning("TwitterRSSScraper: request failed for %s: %s", self.url, exc)
            return []

        content_type = resp.headers.get("content-type", "")
        body = resp.text

        # Detect non-RSS responses (HTML error pages, etc.)
        if "<?xml" not in body and "<rss" not in body and "<feed" not in body:
            logger.warning("TwitterRSSScraper: non-RSS response from %s (type=%s)", self.url, content_type)
            return []

        feed = feedparser.parse(body)
        if not feed.entries:
            logger.info("TwitterRSSScraper: no entries from %s", self.url)
            return []

        entries: list[dict[str, Any]] = []
        for entry in feed.entries[: self.fetch_limit]:
            parsed = self._parse_entry(entry)
            if parsed:
                entries.append(parsed)

        logger.info(
            "TwitterRSSScraper: fetched %d tweets from @%s (%s)",
            len(entries),
            self.username or "unknown",
            self.url,
        )
        return entries

    # ── Parse ───────────────────────────────────────────────────────

    def _parse_entry(self, entry: dict) -> Optional[dict[str, Any]]:
        """Parse a single RSS entry from xgo.ing into a normalised dict."""
        title = entry.get("title", "").strip()
        link = entry.get("link", "").strip()
        summary = entry.get("summary", "") or entry.get("description", "")
        summary = _clean_tweet_text(summary)

        # If no title, use first line of summary
        if not title:
            title = summary[:80].strip()
            if len(summary) > 80:
                title += "..."

        if not title and not summary:
            return None

        # Author
        author = ""
        if hasattr(entry, "author") and entry.author:
            author = entry.author.strip()
        elif hasattr(entry, "author_detail") and entry.author_detail:
            author = entry.author_detail.get("name", "").strip()

        # If we know the username from URL, use it
        if not author and self.username:
            author = f"@{self.username}"

        # Filter retweets if configured
        if not self.include_retweets:
            title_lower = title.lower()
            summary_lower = summary.lower()
            if title_lower.startswith("rt @") or "retweeted" in title_lower:
                return None
            # Also check if the entry is a RT by checking the link pattern
            if "/status/" in link and summary_lower.startswith("rt "):
                return None

        # Published date
        # 注意: content.published_at 列是 TIMESTAMP WITHOUT TIME ZONE (naive).
        published_at = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                published_at = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
        if published_at is None and hasattr(entry, "updated_parsed") and entry.updated_parsed:
            try:
                published_at = datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
            except Exception:
                pass
        if published_at is None:
            published_at = datetime.now(timezone.utc)

        # Tags
        tags = []
        for tag in entry.get("tags", []):
            term = tag.get("term", "").strip()
            if term:
                tags.append(term)
        tags = self._safe_tags({"tags": tags}, max_tags=5)

        # Cover image from media or enclosures
        cover_url = None
        if hasattr(entry, "media_content") and entry.media_content:
            cover_url = entry.media_content[0].get("url")
        elif hasattr(entry, "enclosures") and entry.enclosures:
            for enc in entry.enclosures:
                if enc.get("type", "").startswith("image"):
                    cover_url = enc.get("href") or enc.get("url")
                    break

        # Build raw_content with full tweet text
        raw_content = summary
        if len(raw_content) > 2000:
            raw_content = raw_content[:1997] + "..."

        # Extract tweet ID from link for metadata
        tweet_id = ""
        tweet_match = re.search(r"/status/(\d+)", link)
        if tweet_match:
            tweet_id = tweet_match.group(1)

        return {
            "title": title,
            "url": link,
            "author": author,
            "summary": summary[:500] if summary else title,
            "raw_content": raw_content or None,
            "tags": tags,
            "published_at": published_at,
            "cover_url": cover_url,
            # Twitter-specific metadata for scoring engine
            "_twitter_rss_meta": {
                "username": self.username,
                "tweet_id": tweet_id,
                "has_media": cover_url is not None,
            },
        }
