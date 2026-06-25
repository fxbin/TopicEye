"""trending_pipeline 单测: 聚焦 sync_all_trending 的并发行为。

重点验证并发改造 (gather + Semaphore) 的三个性质:
1. 真并发: 多源总耗时 ≈ max(单源), 不是 sum(单源)
2. 错误隔离: 一个源抛异常, 其他源仍正常入库
3. 并发度配置 clamp 到 [1, 20]

用 monkeypatch 把 pipeline 模块里的 async_session 替换成测试 session 工厂,
让并发的 sync_one 连到 conftest 的 in-memory SQLite。
"""

from __future__ import annotations

import asyncio
import time

import pytest

from app.services import trending_pipeline as pipeline
from app.services.trending_pipeline import sync_all_trending, _normalize_trending_concurrency


# ── 测试用假 scraper ─────────────────────────────────────────────


class _FakeScraper:
    """可控的假 scraper: 固定耗时 + 可选异常 + 固定返回条目。

    pipeline 会 scraper_cls() 实例化, 所以本对象需要可调用 (返回自身)。
    """

    def __init__(self, delay: float, entries=None, exc=None, category="hot"):
        self._delay = delay
        self._entries = entries
        self._exc = exc
        self.CATEGORY = category
        self.SOURCE = "fake"

    def __call__(self):
        # pipeline 调 scraper_cls() 拿实例; 这里返回自身
        return self

    async def fetch(self, client):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc:
            raise self._exc
        return self._entries or []


def _patch_sources(monkeypatch, scraper_map: dict[str, _FakeScraper]):
    """patch get_all_trending_sources + get_trending_cls。"""
    monkeypatch.setattr(
        pipeline, "get_all_trending_sources", lambda: list(scraper_map.keys())
    )
    monkeypatch.setattr(
        pipeline, "get_trending_cls", lambda name: scraper_map.get(name)
    )


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_all_runs_concurrently_not_sequentially(
    db, test_session_factory, monkeypatch
):
    """两个源各 sleep 0.4s, 串行需 ~0.8s, 并发(≥2)应 < 0.7s。"""
    # pipeline 内部用 async_session() 开独立 session, patch 到测试工厂
    monkeypatch.setattr(pipeline, "async_session", test_session_factory)
    monkeypatch.setattr(pipeline, "_normalize_trending_concurrency", lambda: 8)

    entries = [{"title": f"item-{i}", "rank": i, "hot_value": i} for i in range(3)]
    _patch_sources(monkeypatch, {
        "src_a": _FakeScraper(delay=0.4, entries=entries),
        "src_b": _FakeScraper(delay=0.4, entries=entries),
    })

    t = time.monotonic()
    results = await sync_all_trending(db)
    elapsed = time.monotonic() - t

    # 真并发: 两源各 0.4s, 总耗时应明显 < 串行 0.8s (留余量到 0.7s)
    assert elapsed < 0.7, f"expected concurrent (<0.7s), got {elapsed:.2f}s"
    assert results["src_a"]["fetched"] == 3
    assert results["src_b"]["fetched"] == 3


@pytest.mark.asyncio
async def test_sync_all_isolates_per_source_failure(
    db, test_session_factory, monkeypatch
):
    """src_bad 抛异常, src_good 应仍正常入库、返回 fetched。"""
    monkeypatch.setattr(pipeline, "async_session", test_session_factory)
    monkeypatch.setattr(pipeline, "_normalize_trending_concurrency", lambda: 8)

    entries = [{"title": "good-item", "rank": 1, "hot_value": 100}]
    _patch_sources(monkeypatch, {
        "src_bad": _FakeScraper(delay=0, exc=RuntimeError("boom")),
        "src_good": _FakeScraper(delay=0, entries=entries),
    })

    results = await sync_all_trending(db)

    # 失败源: sync_trending_source 内部捕获异常、返回 error 字段, 不向上抛
    assert results["src_bad"]["fetched"] == 0
    assert "boom" in results["src_bad"]["error"]
    # 正常源: 不受影响
    assert results["src_good"]["fetched"] == 1


@pytest.mark.asyncio
async def test_sync_all_handles_empty_source_list(db, monkeypatch):
    """无 source 时返回空 dict, 不报错。"""
    monkeypatch.setattr(pipeline, "get_all_trending_sources", lambda: [])
    results = await sync_all_trending(db)
    assert results == {}


def test_normalize_trending_concurrency_clamps(monkeypatch):
    """并发度配置 clamp 到 [1, 20]。"""
    # 正常值直通
    monkeypatch.setattr(pipeline.settings, "TRENDING_SYNC_CONCURRENCY", 5)
    assert _normalize_trending_concurrency() == 5
    # 下限
    monkeypatch.setattr(pipeline.settings, "TRENDING_SYNC_CONCURRENCY", 0)
    assert _normalize_trending_concurrency() == 1
    # 上限
    monkeypatch.setattr(pipeline.settings, "TRENDING_SYNC_CONCURRENCY", 99)
    assert _normalize_trending_concurrency() == 20
    # 非法值回退默认
    monkeypatch.setattr(pipeline.settings, "TRENDING_SYNC_CONCURRENCY", "not-a-number")
    assert _normalize_trending_concurrency() == 8
