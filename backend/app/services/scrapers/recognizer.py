"""
URL → SourceType recognizer.

Pure-function, table-driven URL pattern matching. Used by import_opml /
batch import to pick the right scraper without asking the user to specify
source_type manually. Migrated from the hard-coded `xgo.ing` branch in
``app/api/v1/sources.py`` (T1-3b) and extended to YouTube / Podcast /
Newsletter / RSS feeds.

Returned tuple: ``(source_type, normalized_url, extra_keyword_config)``.
The third element (dict or None) is JSON-serialised into ``Source.keyword``
and read back by the matching scraper's ``__init__``.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlparse

from app.models.source import SourceType


def recognize_source_type(
    url: str,
    *,
    name: Optional[str] = None,
) -> tuple[SourceType, str, Optional[dict]]:
    """Infer ``SourceType`` from a feed/page URL.

    Args:
        url: the source URL the user pasted (RSS feed, channel page, etc).
        name: optional display name. Used to extract ``@handle`` for xgo.ing
            Twitter RSS feeds where the handle is in the name rather than URL.

    Returns:
        ``(source_type, normalized_url, extra_config)``.

        - ``source_type`` is always set (defaults to :class:`SourceType.RSS`).
        - ``normalized_url`` is the URL to store (currently always the input;
          future revisions may rewrite e.g. bare handles).
        - ``extra_config`` is a dict serialised into ``Source.keyword`` when
          the scraper needs additional metadata (e.g. ``screen_name`` for
          Twitter RSS, ``channel_id`` for YouTube). ``None`` otherwise.
    """
    if not url:
        return SourceType.RSS, url, None

    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    # ── Twitter RSS via xgo.ing bridge ─────────────────────────────────
    if "xgo.ing" in host:
        screen_name = ""
        if name:
            # name like "OpenAI(@OpenAI)" or "OpenAI (@openai)"
            handle_match = re.search(r"\(@?(\w+)\)", name)
            if handle_match:
                screen_name = handle_match.group(1)
        if not screen_name:
            # fall back to path segment: xgo.ing/<user>/rss
            seg_match = re.search(r"xgo\.ing/([^/?#\s]+)", url, re.IGNORECASE)
            if seg_match and seg_match.group(1).lower() not in {"rss", "api"}:
                screen_name = seg_match.group(1)
        config = {"screen_name": screen_name} if screen_name else None
        return SourceType.TWITTER_RSS, url, config

    # ── YouTube ────────────────────────────────────────────────────────
    if host in {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}:
        # Already an RSS feed URL?
        m = re.search(r"channel_id=([A-Za-z0-9_-]+)", url)
        if m:
            return SourceType.YOUTUBE, url, {"channel_id": m.group(1)}
        # /channel/UCxxxx
        m = re.match(r"^/channel/([A-Za-z0-9_-]+)", path)
        if m:
            return SourceType.YOUTUBE, url, {"channel_id": m.group(1)}
        # /@handle or /user/name — scraper resolves channel_id at fetch time
        if re.match(r"^/@[\w.\-]+", path) or re.match(r"^/user/[^/]+", path):
            return SourceType.YOUTUBE, url, None
        # youtu.be/<video> — single video, treat as YouTube anyway
        if host == "youtu.be" and path.strip("/"):
            return SourceType.YOUTUBE, url, None
        return SourceType.YOUTUBE, url, None

    # ── Podcast ────────────────────────────────────────────────────────
    if host == "podcasts.apple.com" or host == "itunes.apple.com":
        # /us/podcast/<slug>/id<id>
        m = re.search(r"/id(\d+)", path)
        config = {"itunes_id": m.group(1)} if m else None
        return SourceType.PODCAST, url, config
    if host == "xiaoyuzhoufm.com" or host.endswith(".xiaoyuzhoufm.com"):
        return SourceType.PODCAST, url, None
    if host.endswith(".buzzsprout.com"):
        return SourceType.PODCAST, url, None
    if host.endswith(".podbean.com"):
        return SourceType.PODCAST, url, None
    if host in {"anchor.fm", "www.anchor.fm"} or host.endswith(".anchor.fm"):
        return SourceType.PODCAST, url, None
    if host in {"open.spotify.com"} and path.startswith("/show/"):
        return SourceType.PODCAST, url, None

    # ── Newsletter ─────────────────────────────────────────────────────
    if host == "buttondown.email":
        # buttondown.email/<name>
        m = re.match(r"^/([^/?#\s]+)", path)
        if m and m.group(1).lower() not in {"login", "signup", "about"}:
            return SourceType.NEWSLETTER, url, None
        return SourceType.NEWSLETTER, url, None
    if host.endswith(".substack.com"):
        return SourceType.NEWSLETTER, url, None
    if host.endswith(".beehiiv.com"):
        return SourceType.NEWSLETTER, url, None
    if host == "tinyletter.com" or host.endswith(".tinyletter.com"):
        return SourceType.NEWSLETTER, url, None
    if host == "convertkit.com" or host.endswith(".convertkit.com"):
        return SourceType.NEWSLETTER, url, None

    # ── RSS fallback (default + explicit feed hints) ───────────────────
    # Explicit RSS feed hints — keep as RSS but more confident.
    if host.startswith("feeds.") or path.endswith((".xml", ".rss", ".atom")) or "/feed" in path or "/rss" in path:
        return SourceType.RSS, url, None

    return SourceType.RSS, url, None
