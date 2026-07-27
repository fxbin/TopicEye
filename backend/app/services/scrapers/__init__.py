"""
Scraper base class and registry.

All content source scrapers inherit from BaseScraper and register
themselves so the pipeline can dispatch by SourceType automatically.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.core.http_retry import retry_async

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────

_SCRAPER_REGISTRY: dict[str, type] = {}


def register_scraper(source_type: str):
    """Decorator: register a scraper class for a given source_type string."""

    def _cls(cls):
        _SCRAPER_REGISTRY[source_type] = cls
        return cls

    return _cls


def get_scraper_cls(source_type: str) -> type | None:
    """Look up the scraper class for a source type.

    Tries exact match first, then case-insensitive fallback.
    """
    cls = _SCRAPER_REGISTRY.get(source_type)
    if cls is not None:
        return cls
    # Case-insensitive fallback: "Reddit" -> "REDDIT"
    upper = source_type.upper()
    for key, val in _SCRAPER_REGISTRY.items():
        if key.upper() == upper:
            return val
    return None


# ── Base class ────────────────────────────────────────────────────────


class BaseScraper(ABC):
    """
    Abstract base scraper.

    Each scraper must implement ``fetch`` which returns a list of normalised
    entry dicts ready for the ingestion pipeline.
    """

    def __init__(self, source_url: str, source_config: dict[str, Any] | None = None):
        self.url = source_url
        self.config = source_config or {}

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient):
        """
        Fetch entries from the source.

        Returns a list of dicts with keys:
            title, url, author, summary, raw_content, tags,
            published_at, cover_url
        """
        ...

    @staticmethod
    def _safe_tags(entry: dict, max_tags: int = 5):
        """Extract tags from entry, deduplicated and capped."""
        raw = entry.get("tags", [])
        seen = set()
        result = []
        for t in raw:
            t = t.strip()
            if t and t.lower() not in seen:
                seen.add(t.lower())
                result.append(t)
                if len(result) >= max_tags:
                    break
        return result


# ── Shared feed fetcher with retry ────────────────────────────────────

# Transient HTTP status codes that warrant a retry.
_RETRY_STATUS = {502, 503, 504, 429, 500}


async def fetch_feed_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    etag: str | None = None,
    last_modified: str | None = None,
    attempts: int = 3,
    base_delay: float = 1.0,
    context: str = "",
) -> httpx.Response | None:
    """GET an RSS/Atom feed with retry on transient HTTP errors.

    - Sends ``If-None-Match`` / ``If-Modified-Since`` when etag/last_modified
      are provided, enabling 304 Not Modified short-circuit.
    - Retries on 502/503/504/429/500 and network timeouts with linear backoff.
    - Returns the ``httpx.Response`` on success (200 or 304).
    - Returns ``None`` if all attempts are exhausted (caller treats as "no entries").

    This replaces the bare ``client.get() + raise_for_status()`` pattern that
    immediately fails on transient 502 Bad Gateway from upstream feed servers
    like hnrss.org.
    """
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified

    async def _do_get() -> httpx.Response:
        resp = await client.get(url, headers=headers or None)
        # 304 is a success — return without raising.
        if resp.status_code == 304:
            return resp
        # Transient server errors → raise to trigger retry.
        if resp.status_code in _RETRY_STATUS:
            raise httpx.HTTPStatusError(
                f"HTTP {resp.status_code}",
                request=resp.request,
                response=resp,
            )
        # Other non-2xx → raise (will also be retried, which is fine
        # because persistent 4xx errors will exhaust quickly).
        resp.raise_for_status()
        return resp

    return await retry_async(
        _do_get,
        attempts=attempts,
        base_delay=base_delay,
        context=context or f"RSS feed {url}",
    )


# ── Auto-import submodules to trigger @register_scraper ───────────────

from . import (
    api_source as _api_source_mod,  # noqa: E402, F401
    douyin_hot as _douyin_hot_mod,  # noqa: E402, F401
    newsletter as _newsletter_mod,  # noqa: E402, F401
    podcast as _podcast_mod,  # noqa: E402, F401
    reddit as _reddit_mod,  # noqa: E402, F401
    rss as _rss_mod,  # noqa: E402, F401
    rsshub as _rsshub_mod,  # noqa: E402, F401
    twitter as _twitter_mod,  # noqa: E402, F401
    twitter_rss as _twitter_rss_mod,  # noqa: E402, F401
    website as _website_mod,  # noqa: E402, F401
    youtube as _youtube_mod,  # noqa: E402, F401
    zhihu as _zhihu_mod,  # noqa: E402, F401
)
