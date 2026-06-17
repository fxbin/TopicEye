"""
Tests for the Podcast scraper (T1-3b).
"""

import json
from typing import Optional

import pytest

from app.services.scrapers import get_scraper_cls
from app.services.scrapers.podcast import PodcastScraper


class FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = "", json_data=None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._json or {}


class FakeClient:
    """Routes requests by URL prefix to canned responses."""

    def __init__(self, *, routes=None, default_status: int = 404):
        # routes: dict[url_prefix, FakeResponse]
        self._routes = routes or {}
        self._default_status = default_status
        self.requested_urls = []

    async def get(self, url, **kwargs):
        self.requested_urls.append(url)
        for prefix, resp in self._routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResponse(status_code=self._default_status, text="")


SAMPLE_PODCAST_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Test Podcast</title>
    <item>
      <title>Episode 1</title>
      <link>https://example.com/ep1</link>
      <pubDate>Mon, 12 May 2025 09:00:00 +0000</pubDate>
      <description>First episode</description>
      <enclosure url="https://example.com/audio/ep1.mp3" type="audio/mpeg"/>
    </item>
    <item>
      <title>Episode 2</title>
      <link>https://example.com/ep2</link>
      <pubDate>Tue, 13 May 2025 09:00:00 +0000</pubDate>
      <description>Second episode</description>
    </item>
  </channel>
</rss>
"""

ITUNES_LOOKUP_JSON = {
    "results": [
        {
            "collectionId": 1234567890,
            "trackName": "Test Podcast",
            "feedUrl": "https://feeds.example.com/test-podcast.xml",
        }
    ]
}


def test_podcast_is_registered():
    assert get_scraper_cls("Podcast") is PodcastScraper
    assert get_scraper_cls("PODCAST") is PodcastScraper


@pytest.mark.asyncio
async def test_resolve_rss_url_directly_for_xml():
    """If the URL is already an RSS feed (.xml), use it directly."""
    scraper = PodcastScraper("https://example.com/feed.xml")
    client = FakeClient()
    rss = await scraper._resolve_rss_url(client)
    assert rss == "https://example.com/feed.xml"


@pytest.mark.asyncio
async def test_resolve_rss_url_apple_podcast_via_itunes_lookup():
    """Apple Podcast URL → iTunes lookup → feedUrl."""
    scraper = PodcastScraper(
        "https://podcasts.apple.com/us/podcast/test/id1234567890",
        source_config={"itunes_id": "1234567890"},
    )
    client = FakeClient(
        routes={
            "https://itunes.apple.com/lookup": FakeResponse(json_data=ITUNES_LOOKUP_JSON),
        }
    )
    rss = await scraper._resolve_rss_url(client)
    assert rss == "https://feeds.example.com/test-podcast.xml"
    # Confirm the lookup URL was requested
    assert any("itunes.apple.com/lookup" in u for u in client.requested_urls)


@pytest.mark.asyncio
async def test_resolve_rss_url_apple_id_extracted_from_url():
    """iTunes_id is not in source_config but is in URL path."""
    scraper = PodcastScraper("https://podcasts.apple.com/us/podcast/test/id9999888877")
    client = FakeClient(
        routes={
            "https://itunes.apple.com/lookup": FakeResponse(json_data=ITUNES_LOOKUP_JSON),
        }
    )
    rss = await scraper._resolve_rss_url(client)
    # lookup was called
    assert any("id=9999888877" in u for u in client.requested_urls)


@pytest.mark.asyncio
async def test_fetch_uses_resolved_rss_and_parses_entries():
    """Full fetch path: config has resolved_rss_url → GET → parse."""
    scraper = PodcastScraper(
        "https://podcasts.apple.com/us/podcast/test/id1234567890",
        source_config={"resolved_rss_url": "https://feeds.example.com/test-podcast.xml"},
    )
    client = FakeClient(
        routes={
            "https://feeds.example.com/": FakeResponse(text=SAMPLE_PODCAST_FEED),
        }
    )
    entries = await scraper.fetch(client)

    assert len(entries) == 2
    assert entries[0]["title"] == "Episode 1"
    assert entries[0]["url"] == "https://example.com/ep1"
    assert entries[1]["title"] == "Episode 2"


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_304():
    scraper = PodcastScraper(
        "https://example.com/feed.xml",
        source_config={"resolved_rss_url": "https://example.com/feed.xml"},
    )
    client = FakeClient(
        routes={
            "https://example.com/": FakeResponse(status_code=304),
        }
    )
    entries = await scraper.fetch(client)
    assert entries == []


@pytest.mark.asyncio
async def test_resolve_rss_url_html_extraction_fallback():
    """Generic URL — extract RSS from page HTML."""
    html = """
    <html><head>
      <link rel="alternate" type="application/rss+xml"
            href="https://example.com/show/feed.xml"/>
    </head><body>...</body></html>
    """
    scraper = PodcastScraper("https://example.com/show")
    client = FakeClient(
        routes={
            "https://example.com/show": FakeResponse(text=html),
        }
    )
    rss = await scraper._resolve_rss_url(client)
    assert rss == "https://example.com/show/feed.xml"


@pytest.mark.asyncio
async def test_resolve_rss_url_falls_back_to_input_on_failure():
    """If everything fails, the input URL is returned as a last resort."""
    scraper = PodcastScraper("https://example.com/unknown-page")
    client = FakeClient(default_status=500)
    rss = await scraper._resolve_rss_url(client)
    # No .xml suffix, no itunes match, no HTML extraction → return input
    assert rss == "https://example.com/unknown-page"
