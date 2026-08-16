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
from app.services.trending_pipeline import _normalize_trending_concurrency, sync_all_trending

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
    """patch get_syncable_trending_sources + get_trending_cls。"""
    monkeypatch.setattr(pipeline, "get_syncable_trending_sources", lambda: list(scraper_map.keys()))
    monkeypatch.setattr(pipeline, "get_trending_cls", lambda name: scraper_map.get(name))


# ── Tests ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sync_all_runs_concurrently_not_sequentially(db, test_session_factory, monkeypatch):
    """两个源各 sleep 0.4s, 串行需 ~0.8s, 并发(≥2)应 < 0.7s。"""
    # pipeline 内部用 async_session() 开独立 session, patch 到测试工厂
    monkeypatch.setattr(pipeline, "async_session", test_session_factory)
    monkeypatch.setattr(pipeline, "_normalize_trending_concurrency", lambda: 8)

    entries = [{"title": f"item-{i}", "rank": i, "hot_value": i} for i in range(3)]
    _patch_sources(
        monkeypatch,
        {
            "src_a": _FakeScraper(delay=0.4, entries=entries),
            "src_b": _FakeScraper(delay=0.4, entries=entries),
        },
    )

    t = time.monotonic()
    results = await sync_all_trending(db)
    elapsed = time.monotonic() - t

    # 真并发: 两源各 0.4s, 总耗时应明显 < 串行 0.8s (留余量到 0.7s)
    assert elapsed < 0.7, f"expected concurrent (<0.7s), got {elapsed:.2f}s"
    assert results["src_a"]["fetched"] == 3
    assert results["src_b"]["fetched"] == 3


@pytest.mark.asyncio
async def test_sync_all_isolates_per_source_failure(db, test_session_factory, monkeypatch):
    """src_bad 抛异常, src_good 应仍正常入库、返回 fetched。"""
    monkeypatch.setattr(pipeline, "async_session", test_session_factory)
    monkeypatch.setattr(pipeline, "_normalize_trending_concurrency", lambda: 8)

    entries = [{"title": "good-item", "rank": 1, "hot_value": 100}]
    _patch_sources(
        monkeypatch,
        {
            "src_bad": _FakeScraper(delay=0, exc=RuntimeError("boom")),
            "src_good": _FakeScraper(delay=0, entries=entries),
        },
    )

    results = await sync_all_trending(db)

    # 失败源: sync_trending_source 内部捕获异常、返回 error 字段, 不向上抛
    assert results["src_bad"]["fetched"] == 0
    assert "boom" in results["src_bad"]["error"]
    # 正常源: 不受影响
    assert results["src_good"]["fetched"] == 1


@pytest.mark.asyncio
async def test_sync_all_handles_empty_source_list(db, monkeypatch):
    """无 source 时返回空 dict, 不报错。"""
    monkeypatch.setattr(pipeline, "get_syncable_trending_sources", lambda: [])
    results = await sync_all_trending(db)
    assert results == {}


def test_syncable_sources_excludes_webnovel():
    """定时同步排除网文书库类重源 (heiyan/ishugui), 但手动单刷不受影响。"""
    from app.services.trending_scrapers import (
        SYNC_EXCLUDED_SOURCES,
        get_all_trending_sources,
        get_syncable_trending_sources,
    )

    all_sources = set(get_all_trending_sources())
    syncable = set(get_syncable_trending_sources())

    # 网文源注册了 (手动单刷仍可用), 但不在 syncable 列表
    assert "heiyan" in all_sources
    assert "ishugui" in all_sources
    assert "heiyan" not in syncable
    assert "ishugui" not in syncable
    # 其余源保留
    assert syncable == all_sources - SYNC_EXCLUDED_SOURCES
    assert "xyzrank" in syncable
    assert "github" in syncable


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


@pytest.mark.asyncio
async def test_same_source_sync_is_serialized_by_lock(db, test_session_factory, monkeypatch):
    """per-source 锁: 同一 source 的两次并发 sync 会被串行化, 不同 source 不互斥。

    场景: 手动单刷 /sync/weibo 与定时全量里的 weibo 并发。
    """
    import asyncio as _asyncio

    from app.services import trending_pipeline as tp

    monkeypatch.setattr(tp, "async_session", test_session_factory)
    monkeypatch.setattr(tp, "_normalize_trending_concurrency", lambda: 8)

    # 用一个会记录并发数的假 scraper
    in_flight = 0
    max_concurrent = 0

    class _CountingScraper:
        CATEGORY = "hot"
        SOURCE = "weibo"

        def __call__(self):
            return self

        async def fetch(self, client):
            nonlocal in_flight, max_concurrent
            in_flight += 1
            max_concurrent = max(max_concurrent, in_flight)
            await _asyncio.sleep(0.15)  # 模拟抓取耗时
            in_flight -= 1
            return [{"title": "x", "rank": 1, "hot_value": 1}]

    monkeypatch.setattr(tp, "get_trending_cls", lambda name: _CountingScraper())
    monkeypatch.setattr(tp, "get_syncable_trending_sources", lambda: ["weibo"])

    # 并发触发同一 source 的两次 sync
    await _asyncio.gather(
        tp.sync_trending_source("weibo", db),
        tp.sync_trending_source("weibo", db),
    )

    # 锁生效: 两次 fetch 不会重叠, max_concurrent 应为 1
    assert max_concurrent == 1, f"expected serialized (max_concurrent=1), got {max_concurrent}"
