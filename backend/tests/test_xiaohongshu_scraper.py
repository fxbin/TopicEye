"""xiaohongshu 热榜 scraper 单测: payload 解析 + 降级容错.

全部用 FakeClient mock, 不真发请求. 字段结构取自 60s API 源码
(rednote.module.ts) 的响应构造.
"""

from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.services.trending_scrapers._xiaohongshu import (
    XiaohongshuTrending,
    _parse_hot_value,
)


# ── Fake client ─────────────────────────────────────────────────
class FakeClient:
    """模拟 httpx.AsyncClient.get: 按 url 返回排队好的 payload.

    payload 可以是 dict (200 JSON)、(status, dict) 元组 (自定义状态码)
    或 Exception (网络层失败).
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url, **kwargs):
        self.calls.append(url)
        if not self.responses:
            raise RuntimeError("FakeClient: no more responses queued")
        match, payload = self.responses.pop(0)
        if match and match not in url:
            raise AssertionError(f"FakeClient: expected url containing {match!r}, got {url!r}")
        if isinstance(payload, Exception):
            raise payload
        request = httpx.Request("GET", url)
        if isinstance(payload, tuple):
            status, body = payload
            return httpx.Response(status, json=body, request=request)
        return httpx.Response(200, json=payload, request=request)


def _item(title="秋天的第一顿螃蟹", **overrides):
    """构造一条标准榜单条目 (字段取自 60s rednote.module.ts)."""
    base = {
        "rank": 1,
        "title": title,
        "score": "1289600",
        "word_type": "hot",
        "work_type_icon": "https://picasso-static.xiaohongshu.com/icon.png",
        "link": "https://www.xiaohongshu.com/search_result?keyword=%E8%9E%83%E8%9F%B9&type=51",
    }
    base.update(overrides)
    return base


def _ok_payload(items):
    return {"code": 200, "message": "OK", "name": "小红书实时热点", "data": items}


# ── 解析 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_parses_standard_payload():
    client = FakeClient([("rednote", _ok_payload([_item(), _item("一周穿搭灵感", rank=2, score=880000)]))])
    entries = await XiaohongshuTrending().fetch(client)

    assert len(entries) == 2
    first = entries[0]
    assert first["title"] == "秋天的第一顿螃蟹"
    assert first["rank"] == 1
    assert first["url"].startswith("https://www.xiaohongshu.com/search_result")
    assert first["hot_value"] == 1289600
    assert first["hot_value_raw"] == "1289600"
    assert first["trend"] == "stable"
    assert first["cover_url"] == "https://picasso-static.xiaohongshu.com/icon.png"
    assert first["extra"] == {"word_type": "hot"}
    # score 为数字时同样解析
    assert entries[1]["hot_value"] == 880000


@pytest.mark.asyncio
async def test_fetch_uses_configured_base_url(monkeypatch):
    monkeypatch.setattr(settings, "API60S_BASE_URL", "https://example.invalid/")
    client = FakeClient([("rednote", _ok_payload([_item()]))])
    await XiaohongshuTrending().fetch(client)
    # 尾部斜杠被清理，路径拼 /v2/rednote
    assert client.calls == ["https://example.invalid/v2/rednote"]


@pytest.mark.asyncio
async def test_fetch_skips_items_without_title():
    items = [_item(), _item("", rank=2), {"rank": 3}]
    client = FakeClient([("rednote", _ok_payload(items))])
    entries = await XiaohongshuTrending().fetch(client)
    assert len(entries) == 1


@pytest.mark.asyncio
async def test_fetch_ranks_fall_back_to_position():
    item = _item()
    item.pop("rank")
    client = FakeClient([("rednote", _ok_payload([item]))])
    entries = await XiaohongshuTrending().fetch(client)
    assert entries[0]["rank"] == 1


# ── 降级 ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_degrades_on_http_500():
    # 上游渠道故障时 60s 返回 HTTP 500（接入时点的真实行为）
    client = FakeClient([("rednote", (500, {"code": 500, "message": "服务器出错了", "data": None}))])
    assert await XiaohongshuTrending().fetch(client) == []


@pytest.mark.asyncio
async def test_fetch_degrades_on_error_code_with_http_200():
    client = FakeClient([("rednote", (200, {"code": 500, "message": "服务器出错了", "data": None}))])
    assert await XiaohongshuTrending().fetch(client) == []


@pytest.mark.asyncio
async def test_fetch_degrades_on_empty_data():
    client = FakeClient([("rednote", _ok_payload([]))])
    assert await XiaohongshuTrending().fetch(client) == []


@pytest.mark.asyncio
async def test_fetch_degrades_on_network_error():
    client = FakeClient([("rednote", httpx.ConnectError("connection reset"))])
    assert await XiaohongshuTrending().fetch(client) == []


@pytest.mark.asyncio
async def test_fetch_degrades_on_non_json_body():
    class HtmlClient(FakeClient):
        async def get(self, url, **kwargs):
            self.calls.append(url)
            request = httpx.Request("GET", url)
            return httpx.Response(200, text="<html>blocked</html>", request=request)

    assert await XiaohongshuTrending().fetch(HtmlClient([])) == []


# ── score 解析 ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1289600, 1289600),
        (88.5, 88),
        ("1289600", 1289600),
        ("123.4万", 1234000),
        ("  456 ", 456),
        ("", 0),
        ("abc", 0),
        (None, 0),
        (True, 0),
    ],
)
def test_parse_hot_value(raw, expected):
    assert _parse_hot_value(raw) == expected
