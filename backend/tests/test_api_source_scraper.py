import httpx
import pytest

from app.services.scrapers import get_scraper_cls
from app.services.scrapers.api_source import APIScraper


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.last_request = None

    async def request(self, method, url, **kwargs):
        self.last_request = {"method": method, "url": url, **kwargs}
        request = httpx.Request(method, url)
        return httpx.Response(200, json=self.payload, request=request)


@pytest.mark.asyncio
async def test_api_scraper_maps_json_items_with_configured_fields():
    scraper = APIScraper(
        "https://example.com/api/news",
        {
            "headers": {"X-Token": "secret"},
            "items_path": "data.items",
            "fields": {
                "title": "name",
                "url": "link",
                "summary": "desc",
                "published_at": "ts",
                "cover_url": "image.url",
            },
        },
    )
    client = FakeClient(
        {
            "data": {
                "items": [
                    {
                        "name": "第一条",
                        "link": "https://example.com/a",
                        "desc": "摘要",
                        "ts": 1780960043000,
                        "image": {"url": "https://example.com/a.jpg"},
                    }
                ]
            }
        }
    )

    entries = await scraper.fetch(client)

    assert client.last_request["headers"] == {"X-Token": "secret"}
    assert entries[0]["title"] == "第一条"
    assert entries[0]["url"] == "https://example.com/a"
    assert entries[0]["summary"] == "摘要"
    assert entries[0]["cover_url"] == "https://example.com/a.jpg"


def test_api_scraper_is_registered():
    assert get_scraper_cls("API") is APIScraper
