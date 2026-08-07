"""Normalisation for short, display-safe content summaries.

RSS and Atom feeds commonly put HTML in ``description``/``summary``.  A few
feeds (notably Hacker News-style feeds) use that field only for ``Article
URL`` and ``Comments URL`` metadata.  ``ContentItem.summary`` is a concise
plain-text display field, so strip markup and discard those metadata-only
lines before the value enters the content model.

The original item URL remains on ``ContentItem.url`` and article bodies remain
on ``ContentItem.raw_content``; this module deliberately does not process
either of them.
"""

from __future__ import annotations

import re
from html import unescape

from bs4 import BeautifulSoup

_RSS_LINK_METADATA_RE = re.compile(
    r"^\s*(?:article|comments?)\s+url\s*:\s*(?:https?://\S+)?\s*$",
    re.IGNORECASE,
)


def _is_rss_link_metadata(text: str) -> bool:
    """Return whether a complete text block is RSS link metadata, not prose."""
    return bool(_RSS_LINK_METADATA_RE.match(" ".join(text.split())))


def clean_content_summary(value: str | None) -> str:
    """Return readable plain text for a content summary.

    This accepts both literal and entity-escaped HTML, removes unsafe/non-text
    markup, and drops standalone ``Article URL`` / ``Comments URL`` blocks.
    It intentionally keeps ordinary summary prose and does not alter article
    bodies or the canonical content URL.
    """
    if not isinstance(value, str) or not value:
        return ""

    text = unescape(value).strip()
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    for tag in soup(["script", "style", "template"]):
        tag.decompose()

    # Feedparser has already decoded well-formed RSS in most cases, but feeds
    # still vary between <p>, <div>, and list items.  Only remove a block when
    # all of its visible text is one of the known metadata labels.
    for tag in soup.find_all(["p", "div", "li"]):
        if _is_rss_link_metadata(tag.get_text(" ", strip=True)):
            tag.decompose()

    summary = " ".join(soup.get_text(" ", strip=True).split())
    # Inline tags around CJK punctuation otherwise leave an artificial space
    # (for example ``摘要</em>。`` becomes ``摘要 。``).
    summary = re.sub(r"\s+([,.;:!?，。！？；：])", r"\1", summary)
    return "" if _is_rss_link_metadata(summary) else summary
