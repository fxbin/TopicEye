"""heiyan scraper 单测: _build_search_entry 解析 + _fetch_search_all_pages 分页.

PG 迁移期: 全部用 FakeClient mock, 不真发请求.
"""

from __future__ import annotations

import httpx
import pytest

from app.services.trending_scrapers._heiyan import HeiyanTrending


# ── Fake client ─────────────────────────────────────────────────
class FakeClient:
    """模拟 httpx.AsyncClient.get: 按 url 返回排队好的 payload, 排队空时抛错."""

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


def _ok_payload(content, total_pages=None, total_elements=None):
    """构造 /search/new/all 标准成功响应."""
    return {
        "success": True,
        "code": 1,
        "message": "操作成功",
        "data": {
            "content": content,
            "pageable": {"pageNumber": 0, "pageSize": 20},
            "totalElements": total_elements if total_elements is not None else len(content),
            "totalPages": total_pages if total_pages is not None else 1,
            "first": True,
            "last": True,
            "numberOfElements": len(content),
            "size": 20,
            "number": 0,
            "empty": len(content) == 0,
        },
    }


def _book(
    bid: str,
    name: str = "测试书名",
    *,
    tags=None,
    sort_name: str = "现言",
    book_type: int = 1,
    author_name=None,
    intro: str = "测试简介",
):
    return {
        "id": bid,
        "name": name,
        "introduce": intro,
        "tags": tags if tags is not None else "",
        "sortName": sort_name,
        "booktype": book_type,
        "authorid": "1999002464609169410",
        "authorname": author_name,  # 允许为 null
        "iconUrlSmall": f"https://img.zhangwenpindu.cn/book/{bid}.jpg@!bs?1",
        "iconUrlLarge": f"https://img.zhangwenpindu.cn/book/{bid}.jpg@!bl?1",
        "words": 12345,
        "wordsStr": "1.2万字",
        "wxbookid": "wx" + bid,
        "tkbookid": "tk" + bid,
        "finished": True,
        "sort": 1,
    }


# ── _build_search_entry 解析 ──────────────────────────────────
def test_build_search_entry_parses_csv_tags_string():
    """tags='复仇,爽文' 解析为 list[str]."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("1", tags="复仇,爽文"), rank=1)
    assert entry is not None
    assert entry["extra"]["tags"] == ["复仇", "爽文"]


def test_build_search_entry_parses_list_tags():
    """home 形态的 tags list 也能兼容."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("2", tags=["穿越", "反转"]), rank=1)
    assert entry["extra"]["tags"] == ["穿越", "反转"]


def test_build_search_entry_parses_empty_tags():
    """tags 为空字符串 → 空 list (不能 [''])."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("3", tags=""), rank=1)
    assert entry["extra"]["tags"] == []


def test_build_search_entry_propagates_sort_name():
    """sortName='现言' 透传到 extra.sortName."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("4", sort_name="古言"), rank=1)
    assert entry["extra"]["sortName"] == "古言"


def test_build_search_entry_falls_back_when_author_null():
    """authorname=None 时降级为空字符串, 不能写到 extra 里变 null."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("5", author_name=None), rank=1)
    assert entry["extra"]["author"] == ""


def test_build_search_entry_returns_none_when_missing_core_fields():
    """id 或 name 缺失 → 返回 None, 不抛."""
    scraper = HeiyanTrending()
    assert scraper._build_search_entry(_book("6"), rank=1) is not None  # 正常
    bad1 = _book("6")
    bad1.pop("id")
    assert scraper._build_search_entry(bad1, rank=1) is None
    bad2 = _book("7")
    bad2["name"] = "   "
    assert scraper._build_search_entry(bad2, rank=1) is None


def test_build_search_entry_shelf_metadata():
    """shelf 标签固定为「书库全量」/ search_new_all."""
    scraper = HeiyanTrending()
    entry = scraper._build_search_entry(_book("8"), rank=1)
    assert entry["extra"]["shelf"] == "书库全量"
    assert entry["extra"]["shelf_id"] == "search_new_all"
    assert entry["hot_value_raw"] == "书库全量"


# ── _fetch_search_all_pages 分页 ─────────────────────────────
@pytest.mark.asyncio
async def test_fetch_search_all_stops_on_empty_page():
    """page 2 返空 content → 立即停, 不抓 page 3. (终止靠 content 空, 不靠 totalPages)"""
    scraper = HeiyanTrending()
    p0 = _ok_payload([_book("a"), _book("b")], total_pages=10)
    p1 = _ok_payload([_book("c")], total_pages=10)
    p2 = _ok_payload([])  # 空 → 终止
    client = FakeClient(
        [
            ("page=0", p0),
            ("page=1", p1),
            ("page=2", p2),
        ]
    )
    seen: set[str] = set()
    entries = await scraper._fetch_search_all_pages(client, seen, max_pages=12)
    assert len(entries) == 3
    assert [e["extra"]["book_id"] for e in entries] == ["a", "b", "c"]
    # 调了 3 次 (page 0, 1, 2), page=2 空触发终止
    assert len(client.calls) == 3


@pytest.mark.asyncio
async def test_fetch_search_all_dedupes_repeated_page():
    """模拟实测 quirk: page=0 与 page=1 返回相同内容, dedup 后只 1 份."""
    scraper = HeiyanTrending()
    p0 = _ok_payload([_book("dup"), _book("x")], total_pages=10)
    p1 = _ok_payload([_book("dup"), _book("x")], total_pages=10)  # 与 p0 完全相同
    p2 = _ok_payload([_book("y")], total_pages=10)
    p3 = _ok_payload([])
    client = FakeClient(
        [
            ("page=0", p0),
            ("page=1", p1),
            ("page=2", p2),
            ("page=3", p3),
        ]
    )
    seen: set[str] = set()
    entries = await scraper._fetch_search_all_pages(client, seen, max_pages=12)
    # 3 本 (dup, x, y) - p1 重复被 dedup
    assert len(entries) == 3
    assert [e["extra"]["book_id"] for e in entries] == ["dup", "x", "y"]


@pytest.mark.asyncio
async def test_fetch_search_all_dedupes_via_seen():
    """book_id 出现在 seen 里时跳过, rank 不递增."""
    scraper = HeiyanTrending()
    seen = {"shared"}
    p0 = _ok_payload([_book("shared"), _book("new1")], total_pages=10)
    p1 = _ok_payload([])
    client = FakeClient(
        [
            ("page=0", p0),
            ("page=1", p1),
        ]
    )
    entries = await scraper._fetch_search_all_pages(client, seen, max_pages=12)
    assert len(entries) == 1
    assert entries[0]["extra"]["book_id"] == "new1"
    assert entries[0]["rank"] == 1  # 跳过 shared, new1 是合并去重后第 1 个


@pytest.mark.asyncio
async def test_fetch_search_all_retries_on_exception():
    """第 1/2 次抛异常, 第 3 次成功 → 返回数据 (验证 3 次重试)."""
    scraper = HeiyanTrending()
    p0 = _ok_payload([_book("ok")], total_pages=10)
    p1 = _ok_payload([])
    client = FakeClient(
        [
            ("page=0", RuntimeError("conn reset")),
            ("page=0", RuntimeError("timeout")),
            ("page=0", p0),
            ("page=1", p1),
        ]
    )
    seen: set[str] = set()
    entries = await scraper._fetch_search_all_pages(client, seen, max_pages=12)
    assert len(entries) == 1
    assert entries[0]["extra"]["book_id"] == "ok"
    # page=0 重试 3 次 + page=1 终止 = 4 次调用
    assert len(client.calls) == 4


@pytest.mark.asyncio
async def test_fetch_search_all_returns_empty_after_all_retries_fail():
    """3 次重试都失败 → 返回 [], 不 throw."""
    scraper = HeiyanTrending()
    client = FakeClient(
        [
            ("page=0", RuntimeError("e1")),
            ("page=0", RuntimeError("e2")),
            ("page=0", RuntimeError("e3")),
        ]
    )
    seen: set[str] = set()
    entries = await scraper._fetch_search_all_pages(client, seen, max_pages=12)
    assert entries == []
    assert len(client.calls) == 3
