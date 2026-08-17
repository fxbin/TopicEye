"""
Tests for the Newsletter scraper (T1-3b).

Uses the same FakeClient pattern as test_api_source_scraper.py.
"""

import pytest

from app.services.scrapers import get_scraper_cls
from app.services.scrapers.newsletter import NewsletterScraper


class FakeResponse:
    def __init__(self, status_code: int, text: str = ""):
        self.status_code = status_code
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeClient:
    """Fake httpx.AsyncClient. Returns the RSS payload for the normalized URL."""

    def __init__(self, *, payload: str = "", status_code: int = 200):
        self._payload = payload
        self._status_code = status_code
        self.requested_url = None

    async def get(self, url, **kwargs):
        self.requested_url = url
        return FakeResponse(status_code=self._status_code, text=self._payload)


SAMPLE_SUBSTACK_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Test Newsletter</title>
    <item>
      <title>First Issue</title>
      <link>https://test.substack.com/p/first</link>
      <author>editor@test.substack.com</author>
      <pubDate>Mon, 12 May 2025 09:00:00 +0000</pubDate>
      <description>&lt;p&gt;Hello &lt;img src="https://cdn.substack.com/image/abc.png" alt=""&gt;&lt;/p&gt;</description>
    </item>
    <item>
      <title>Second Issue</title>
      <link>https://test.substack.com/p/second</link>
      <author>editor@test.substack.com</author>
      <pubDate>Tue, 13 May 2025 09:00:00 +0000</pubDate>
      <description>&lt;p&gt;World&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""


def test_newsletter_is_registered():
    assert get_scraper_cls("Newsletter") is NewsletterScraper
    # case-insensitive fallback
    assert get_scraper_cls("NEWSLETTER") is NewsletterScraper


@pytest.mark.parametrize(
    "input_url, expected_rss",
    [
        ("https://test.substack.com", "https://test.substack.com/feed"),
        ("https://test.beehiiv.com", "https://test.beehiiv.com/feed"),
        ("https://buttondown.email/sample", "https://buttondown.email/sample/rss"),
        ("https://tinyletter.com/sample", "https://tinyletter.com/sample?format=rss"),
        # Already an RSS URL — kept as-is
        ("https://example.com/news.xml", "https://example.com/news.xml"),
    ],
)
def test_normalize_to_rss(input_url, expected_rss):
    assert NewsletterScraper._normalize_to_rss(input_url) == expected_rss


@pytest.mark.asyncio
async def test_fetch_parses_substack_feed():
    scraper = NewsletterScraper("https://test.substack.com")
    client = FakeClient(payload=SAMPLE_SUBSTACK_FEED)

    entries = await scraper.fetch(client)

    # URL was normalised to the feed endpoint
    assert client.requested_url == "https://test.substack.com/feed"
    assert len(entries) == 2
    assert entries[0]["title"] == "First Issue"
    assert entries[0]["url"] == "https://test.substack.com/p/first"
    # cover_url extracted from <img> tag in summary
    assert entries[0]["cover_url"] == "https://cdn.substack.com/image/abc.png"
    # Second entry has no <img> — cover_url empty
    assert entries[1]["cover_url"] == ""
    assert entries[1]["title"] == "Second Issue"


@pytest.mark.asyncio
async def test_fetch_returns_empty_on_304():
    scraper = NewsletterScraper("https://test.substack.com")
    client = FakeClient(status_code=304)
    entries = await scraper.fetch(client)
    assert entries == []


@pytest.mark.asyncio
async def test_fetch_returns_empty_after_exhausted_retries():
    """重试耗尽后优雅降级为空列表，由 pipeline 统一记录信源错误。"""
    scraper = NewsletterScraper("https://test.substack.com")
    client = FakeClient(status_code=500)
    entries = await scraper.fetch(client)
    assert entries == []
