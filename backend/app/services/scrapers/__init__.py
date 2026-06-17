"""
Scraper base class and registry.

All content source scrapers inherit from BaseScraper and register
themselves so the pipeline can dispatch by SourceType automatically.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

# ── Registry ──────────────────────────────────────────────────────────

_SCRAPER_REGISTRY: Dict[str, type] = {}


def register_scraper(source_type: str):
    """Decorator: register a scraper class for a given source_type string."""

    def _cls(cls):
        _SCRAPER_REGISTRY[source_type] = cls
        return cls

    return _cls


def get_scraper_cls(source_type: str) -> Optional[type]:
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

    def __init__(self, source_url: str, source_config: Optional[Dict[str, Any]] = None):
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


# ── Auto-import submodules to trigger @register_scraper ───────────────

from . import rss as _rss_mod  # noqa: E402, F401
from . import website as _website_mod  # noqa: E402, F401
from . import twitter as _twitter_mod  # noqa: E402, F401
from . import rsshub as _rsshub_mod  # noqa: E402, F401
from . import reddit as _reddit_mod  # noqa: E402, F401
from . import zhihu as _zhihu_mod  # noqa: E402, F401
from . import twitter_rss as _twitter_rss_mod  # noqa: E402, F401
from . import douyin_hot as _douyin_hot_mod  # noqa: E402, F401
from . import api_source as _api_source_mod  # noqa: E402, F401
from . import youtube as _youtube_mod  # noqa: E402, F401
from . import podcast as _podcast_mod  # noqa: E402, F401
from . import newsletter as _newsletter_mod  # noqa: E402, F401
