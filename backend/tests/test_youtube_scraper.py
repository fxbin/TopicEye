"""
Tests for the YouTube scraper (T1-3b).
"""

import pytest

from app.services.scrapers import get_scraper_cls
from app.services.scrapers.youtube import YouTubeScraper


class FakeResponse:
    def __init__(self, *, status_code: int = 200, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Routes by URL prefix to canned responses."""

    def __init__(self, *, routes=None, default_status: int = 404):
        self._routes = routes or {}
        self._default_status = default_status
        self.requested_urls = []

    async def get(self, url, **kwargs):
        self.requested_urls.append(url)
        for prefix, resp in self._routes.items():
            if url.startswith(prefix):
                return resp
        return FakeResponse(status_code=self._default_status, text="")


SAMPLE_YOUTUBE_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns:media="http://search.yahoo.com/mrss/"
      xmlns="http://www.w3.org/2005/Atom">
  <title>Test Channel</title>
  <entry>
    <id>yt:video:abc123</id>
    <title>First Video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=abc123"/>
    <author><name>Test Channel</name></author>
    <published>2025-05-12T09:00:00+00:00</published>
    <media:group>
      <media:title>First Video</media:title>
      <media:description>Description text</media:description>
      <media:thumbnail url="https://i.ytimg.com/vi/abc123/hqdefault.jpg"/>
    </media:group>
  </entry>
  <entry>
    <id>yt:video:def456</id>
    <title>Second Video</title>
    <link rel="alternate" href="https://www.youtube.com/watch?v=def456"/>
    <author><name>Test Channel</name></author>
    <published>2025-05-13T09:00:00+00:00</published>
  </entry>
</feed>
"""

CHANNEL_PAGE_HTML = """
<html><head>
  <meta itemprop="channelId" content="UCabcdefghijklmnopqrstuv">
  <link rel="canonical" href="https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"/>
</head><body>...</body></html>
"""


def test_youtube_is_registered():
    assert get_scraper_cls("YouTube") is YouTubeScraper
    # case-insensitive
    assert get_scraper_cls("YOUTUBE") is YouTubeScraper


def test_extract_channel_id_from_channel_url():
    cid = YouTubeScraper._extract_channel_id_from_url("https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv")
    assert cid == "UCabcdefghijklmnopqrstuv"


def test_extract_channel_id_from_feed_url():
    cid = YouTubeScraper._extract_channel_id_from_url("https://www.youtube.com/feeds/videos.xml?channel_id=UCxyz123")
    assert cid == "UCxyz123"


def test_extract_channel_id_returns_none_for_handle():
    """@handle URLs need network resolution — extraction alone returns None."""
    cid = YouTubeScraper._extract_channel_id_from_url("https://www.youtube.com/@OpenAI")
    assert cid is None


def test_extract_channel_id_returns_none_for_non_youtube():
    cid = YouTubeScraper._extract_channel_id_from_url("https://example.com/feed.xml")
    assert cid is None


@pytest.mark.asyncio
async def test_fetch_uses_pre_resolved_channel_id():
    """source_config carries channel_id — no resolution network call."""
    scraper = YouTubeScraper(
        "https://www.youtube.com/channel/UCabc",
        source_config={"channel_id": "UCabc"},
    )
    client = FakeClient(
        routes={
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCabc": FakeResponse(text=SAMPLE_YOUTUBE_FEED),
        }
    )
    entries = await scraper.fetch(client)

    assert len(entries) == 2
    assert entries[0]["title"] == "First Video"
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=abc123"
    assert entries[0]["author"] == "Test Channel"
    assert entries[0]["cover_url"] == "https://i.ytimg.com/vi/abc123/hqdefault.jpg"
    assert entries[1]["title"] == "Second Video"
    # No page fetch was made — only the feed URL was requested
    assert all("/@openai" not in u.lower() for u in client.requested_urls)


@pytest.mark.asyncio
async def test_fetch_resolves_handle_to_channel_id():
    """@handle URL — scraper fetches the page, extracts channel_id, then RSS."""
    scraper = YouTubeScraper("https://www.youtube.com/@TestChannel")
    client = FakeClient(
        routes={
            "https://www.youtube.com/@TestChannel": FakeResponse(text=CHANNEL_PAGE_HTML),
            "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv": FakeResponse(
                text=SAMPLE_YOUTUBE_FEED
            ),
        }
    )
    entries = await scraper.fetch(client)

    # channel_id was resolved from the HTML meta tag
    assert scraper.channel_id == "UCabcdefghijklmnopqrstuv"
    # Then feed URL was requested
    assert any("channel_id=UCabcdefghijklmnopqrstuv" in u for u in client.requested_urls)
    assert len(entries) == 2


@pytest.mark.asyncio
async def test_fetch_returns_empty_when_channel_id_unresolvable():
    """Resolution fails and no channel_id — return empty list, don't crash."""
    scraper = YouTubeScraper("https://www.youtube.com/@UnknownHandle")
    client = FakeClient(default_status=500)
    entries = await scraper.fetch(client)
    assert entries == []
    assert scraper.channel_id is None


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_304():
    scraper = YouTubeScraper(
        "https://www.youtube.com/channel/UCabc",
        source_config={"channel_id": "UCabc"},
    )
    client = FakeClient(
        routes={
            "https://www.youtube.com/feeds/videos.xml": FakeResponse(status_code=304),
        }
    )
    entries = await scraper.fetch(client)
    assert entries == []
