"""
Website scraper — fetch a single page and extract main content.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.services.extractor import extract_cover_url, extract_main_content

from . import BaseScraper, register_scraper

logger = logging.getLogger(__name__)


@register_scraper("网站")
class WebsiteScraper(BaseScraper):
    """Fetch a single web page and extract content."""

    async def fetch(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        resp = await client.get(self.url)
        resp.raise_for_status()
        html = resp.text

        main_text = extract_main_content(html)
        cover_url = extract_cover_url(html, self.url)

        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else ""

        return [
            {
                "title": title,
                "url": self.url,
                "author": None,
                "summary": main_text[:500] if main_text else "",
                "raw_content": main_text,
                "cover_url": cover_url,
                "published_at": datetime.now(UTC),
            }
        ]
