"""
Web page main-content extractor.

Uses trafilatura for high-quality boilerplate removal and article text
extraction, with a BeautifulSoup fallback for edge cases.
"""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_main_content(html: str) -> str:
    """Extract the main textual content from an HTML page.

    Primary: trafilatura (trained extraction with boilerplate removal).
    Fallback: BeautifulSoup manual extraction for resilience.
    """
    import trafilatura

    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_precision=True,
    )
    if text and len(text.strip()) >= 60:
        return text.strip()

    # Fallback: manual BeautifulSoup extraction
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    for selector in ["article", "[role='main']", ".post-content", ".article-content", ".entry-content", "main"]:
        container = soup.select_one(selector)
        if container:
            return container.get_text(separator="\n", strip=True)

    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)

    return soup.get_text(separator="\n", strip=True)


def extract_cover_url(html: str, base_url: str = "") -> str | None:
    """Try to find the og:image or first large <img> in the page."""
    soup = BeautifulSoup(html, "html.parser")

    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return og["content"]

    twitter = soup.find("meta", attrs={"name": "twitter:image"})
    if twitter and twitter.get("content"):
        return twitter["content"]

    return None
