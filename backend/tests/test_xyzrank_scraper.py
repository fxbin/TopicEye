"""xyzrank scraper 单测: payload 解析 + 异常容错.

全部用 FakeClient mock, 不真发请求.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.trending_scrapers._xyzrank import XyzrankTrending, _fmt_play


# ── Fake client ─────────────────────────────────────────────────
class FakeClient:
    """模拟 httpx.AsyncClient.get: 按 url 返回排队好的 payload."""

    def __init__(self, responses):
        # responses: list of (url_substr, payload_dict | Exception)
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        if not self.responses:
            raise RuntimeError("FakeClient: no more responses queued")
        match, payload = self.responses.pop(0)
        if match and match not in url:
            raise AssertionError(f"FakeClient: expected url containing {match!r}, got {url!r}")
        if isinstance(payload, Exception):
            raise payload
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=payload, request=request)


def _episode(title="vol.51 对谈姜思达", **overrides):
    """构造一条标准 episode payload (字段取自真实 API 响应)."""
    base = {
        "title": title,
        "podcastID": "980f4d8c",
        "podcastName": "天真不天真",
        "logoURL": "https://is1-ssl.mzstatic.com/image/thumb/x.jpg/100x100bb.jpg",
        "link": "https://www.xiaoyuzhoufm.com/episode/6a303f39",
        "playCount": 319377,
        "commentCount": 358,
        "subscription": 2635049,
        "duration": 63,
        "postTime": "2026-06-16T00:00:00.000Z",
        "primaryGenreName": "休闲",
        "totalEpisodesCount": 105,
        "openRate": 0.1212,
        "rank": 1,
    }
    base.update(overrides)
    return base


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_parses_standard_payload():
    """正常 payload: 解析出 title/url/hot_value/cover/extra 全字段."""
    payload = {"items": [_episode(rank=1), _episode(title="E239", rank=2)], "total": 2}
    scraper = XyzrankTrending()
    entries = await scraper.fetch(FakeClient([("api/episodes", payload)]))

    assert len(entries) == 2
    e = entries[0]
    assert e["rank"] == 1
    assert "vol.51 对谈姜思达" in e["title"]
    assert "天真不天真" in e["title"]  # 播客名拼进标题
    assert e["url"] == "https://www.xiaoyuzhoufm.com/episode/6a303f39"
    assert e["hot_value"] == 319377
    assert e["cover_url"] == "https://is1-ssl.mzstatic.com/image/thumb/x.jpg/100x100bb.jpg"
    assert e["trend"] == "stable"
    extra = e["extra"]
    assert extra["podcast_name"] == "天真不天真"
    assert extra["comment_count"] == 358
    assert extra["duration_min"] == 63
    assert extra["genre"] == "休闲"


@pytest.mark.asyncio
async def test_fetch_skips_items_without_title():
    """缺 title 的条目应跳过, 不影响整批."""
    payload = {
        "items": [
            _episode(title="", rank=1),  # 空 title → 跳过
            _episode(title="正常节目", rank=2),
            {"no_title_field": True, "rank": 3},  # 无 title 字段 → 跳过
        ]
    }
    scraper = XyzrankTrending()
    entries = await scraper.fetch(FakeClient([("api/episodes", payload)]))

    assert len(entries) == 1
    assert "正常节目" in entries[0]["title"]


@pytest.mark.asyncio
async def test_fetch_handles_empty_and_malformed_payload():
    """非预期 payload shape (无 items 列表) 应返回空, 不抛异常."""
    scraper = XyzrankTrending()

    # 缺 items 字段
    entries = await scraper.fetch(FakeClient([("api/episodes", {"total": 0})]))
    assert entries == []

    # items 非 list
    entries = await scraper.fetch(FakeClient([("api/episodes", {"items": "oops"})]))
    assert entries == []


@pytest.mark.asyncio
async def test_fetch_network_error_returns_empty():
    """网络异常时返回空列表, 不向上抛."""
    scraper = XyzrankTrending()
    entries = await scraper.fetch(FakeClient([("api/episodes", ConnectionError("boom"))]))
    assert entries == []


def test_fmt_play():
    """播放量中文短文本格式化."""
    assert _fmt_play(319377) == "31.9万播放"
    assert _fmt_play(10000) == "1.0万播放"
    assert _fmt_play(9999) == "9999播放"
    assert _fmt_play(0) == "0播放"
