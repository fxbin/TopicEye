"""
Web page main-content extractor.

Uses BeautifulSoup to strip boilerplate and return the core article text.
"""

from typing import Optional
from bs4 import BeautifulSoup


def extract_main_content(html: str) -> str:
    """Extract the main textual content from an HTML page."""
    soup = BeautifulSoup(html, "html.parser")

    # Remove noise tags
    for tag in soup(["script", "style", "nav", "header", "footer", "aside", "noscript"]):
        tag.decompose()

    # Try common article containers first
    for selector in ["article", "[role='main']", ".post-content", ".article-content", ".entry-content", "main"]:
        container = soup.select_one(selector)
        if container:
            return container.get_text(separator="\n", strip=True)

    # Fallback: body text
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
