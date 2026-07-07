"""番茄小说服务测试。

覆盖:
- _refresh_book_metadata: 元数据刷新（含过期封面 URL）
- fanqie_abogus.generate_a_bogus: 反爬签名生成（结构/可重现性/差异化）
- _build_query_string: 查询串拼接顺序
- fetch_json: a_bogus 仅对 rank 接口附加
"""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from app.services import fanqie_service
from app.services.fanqie_abogus import generate_a_bogus
from app.services.fanqie_service import (
    RANK_URL,
    SIGN_UA,
    _build_query_string,
    _cover_url_is_stale,
    _refresh_book_metadata,
    fetch_json,
)


# ─── _refresh_book_metadata ───────────────────────────────────────────


def test_refresh_book_metadata_updates_expiring_cover_url():
    book = SimpleNamespace(
        book_name="旧书名",
        author="旧作者",
        abstract="旧简介",
        category_id="old",
        category_name="旧分类",
        thumb_uri="https://old.example/cover.image?x-expires=1",
        read_count="10",
        word_number="1000",
        last_chapter_title="旧章节",
        last_chapter_update_time=1,
    )

    _refresh_book_metadata(
        book,
        {
            "bookName": "新书名",
            "author": "新作者",
            "abstract": "新简介",
            "thumbUri": "https://new.example/cover.image?x-expires=9999999999",
            "read_count": 20,
            "wordNumber": 2000,
            "lastChapterTitle": "新章节",
            "lastChapterUpdateTime": 2,
        },
        {"category_id": "new", "category_name": "新分类"},
    )

    assert book.book_name == "新书名"
    assert book.thumb_uri == "https://new.example/cover.image?x-expires=9999999999"
    assert book.category_id == "old"
    assert book.category_name == "旧分类"
    assert book.read_count == "20"
    assert book.word_number == "2000"


def test_refresh_book_metadata_keeps_existing_cover_when_api_returns_empty():
    """API 返回空 thumbUri 时，应保留数据库里既有的 URL（不抹成空）。"""
    book = SimpleNamespace(
        book_name="x",
        author="x",
        abstract="x",
        category_id="c",
        category_name="cat",
        thumb_uri="https://existing.example/cover.png",
        read_count="1",
        word_number="1",
        last_chapter_title="x",
        last_chapter_update_time=0,
    )

    _refresh_book_metadata(book, {"thumbUri": ""}, {})

    assert book.thumb_uri == "https://existing.example/cover.png"


# ─── generate_a_bogus ─────────────────────────────────────────────────


class TestGenerateABogus:
    def test_returns_non_empty_string(self):
        sig = generate_a_bogus("key=value", "test/1.0")
        assert isinstance(sig, str)
        assert len(sig) > 10

    def test_trailing_equals(self):
        """a_bogus 固定以 = 结尾（自定义 base64 填充标识）。"""
        assert generate_a_bogus("a=b", "ua").endswith("=")

    def test_different_params_different_signature(self):
        assert generate_a_bogus("a=1", "ua") != generate_a_bogus("a=2", "ua")

    def test_different_ua_different_signature(self):
        assert generate_a_bogus("a=1", "ua1") != generate_a_bogus("a=1", "ua2")

    def test_chinese_params(self):
        """含中文的查询串也应生成合法签名（SM3 内部做 URL 编码）。"""
        sig = generate_a_bogus("keyword=测试", "Mozilla/5.0")
        assert sig.endswith("=")


# ─── _build_query_string ──────────────────────────────────────────────


def test_build_query_string_preserves_order():
    """查询串必须保持 dict 插入顺序（Python 3.7+ 保证），
    因为 a_bogus 签名与参数顺序绑定。"""
    params = {
        "app_id": 2503,
        "rank_list_type": 3,
        "offset": 0,
        "limit": 100,
        "category_id": 1141,
        "rank_version": "",
        "gender": 1,
        "rankMold": 2,
    }
    qs = _build_query_string(params)
    assert qs == "app_id=2503&rank_list_type=3&offset=0&limit=100&category_id=1141&rank_version=&gender=1&rankMold=2"


# ─── fetch_json: a_bogus 仅对 rank 接口附加 ─────────────────────────


@pytest.mark.asyncio
async def test_fetch_json_attaches_a_bogus_only_for_rank(monkeypatch):
    """验证 fetch_json 仅对 RANK_URL 附加 a_bogus，对其它 URL 不附加。"""
    captured = {}

    class _FakeClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a, **kw):
            return False

        def get(self, url, params=None):
            captured["url"] = url
            captured["params"] = dict(params or {})

            class _Resp:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"ok": True}

            return _Resp()

    monkeypatch.setattr(httpx, "Client", _FakeClient)

    rank_params = {
        "app_id": 2503,
        "category_id": 1141,
        "gender": 1,
        "rankMold": 2,
    }
    await fetch_json(RANK_URL, rank_params)
    assert "a_bogus" in captured["params"]
    assert captured["params"]["a_bogus"]  # non-empty
    assert captured["params"]["category_id"] == 1141  # 其它参数仍保留

    captured.clear()
    await fetch_json(fanqie_service.CATEGORY_URL, {"config_key": "x"})
    assert "a_bogus" not in captured["params"]
    assert captured["params"] == {"config_key": "x"}


@pytest.mark.asyncio
async def test_fetch_json_returns_none_on_exception(monkeypatch):
    """网络异常时返回 None，不抛出。"""

    class _BoomClient:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a, **kw):
            return False

        def get(self, *a, **kw):
            raise httpx.ConnectError("boom")

    monkeypatch.setattr(httpx, "Client", _BoomClient)
    assert await fetch_json(RANK_URL, {"x": 1}) is None


# ─── _cover_url_is_stale ──────────────────────────────────────────────


class TestCoverUrlIsStale:
    """封面 URL 过期检测：番茄 URL 含 x-expires=Unix 时间戳。"""

    def test_stale_when_expired(self):
        """x-expires 已过 → True。"""
        url = "https://p3-reading-sign.fqnovelpic.com/x?x-expires=1000&x-signature=abc"
        assert _cover_url_is_stale(url, now_ts=2000) is True

    def test_stale_when_within_headroom(self):
        """x-expires 在 24h headroom 内 → True（提前判过期留刷新窗口）。"""
        url = "https://x?x-expires=100000"
        # now = 100000 - 3600（差 1 小时，在 headroom 内）
        assert _cover_url_is_stale(url, now_ts=100000 - 3600) is True

    def test_not_stale_when_far_future(self):
        """x-expires 远未到 → False。"""
        url = "https://x?x-expires=1000000"
        assert _cover_url_is_stale(url, now_ts=1000) is False

    def test_not_stale_when_no_expires_param(self):
        """无 x-expires 参数（非签名 URL）→ False，避免误伤。"""
        assert _cover_url_is_stale("https://example.com/cover.png") is False

    def test_not_stale_when_none(self):
        assert _cover_url_is_stale(None) is False

    def test_not_stale_when_empty(self):
        assert _cover_url_is_stale("") is False

    def test_real_url_format(self):
        """真实番茄 URL 格式解析。"""
        # 6/13 抓的 URL，x-expires=1781917201（6/20 过期）
        url = (
            "https://p3-reading-sign.fqnovelpic.com/novel-pic/abc~tplv-resize:225:0.image"
            "?lk3s=5b7047ff&x-expires=1781917201&x-signature=WCZaxx7HurbKG5ftttaj%2FRSW8ks%3D"
        )
        # 模拟 7/8（已过期 17 天）
        import time as _time
        july8 = _time.mktime((2026, 7, 8, 0, 0, 0, 0, 0, 0))
        assert _cover_url_is_stale(url, now_ts=july8) is True
        # 模拟 6/14（抓后 1 天，远未过期）
        june14 = _time.mktime((2026, 6, 14, 0, 0, 0, 0, 0, 0))
        assert _cover_url_is_stale(url, now_ts=june14) is False
