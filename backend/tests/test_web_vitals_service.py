"""前端体验指标口径与聚合的回归测试（#179）。

覆盖三块：

1. **阈值判定**（``classify_metric``）：边界值语义必须与 web-vitals v6 一致
   ——等于 good 上界仍是 good，严格大于才是 needs-improvement。
2. **路径归一**（``normalize_route_path``）：动态段必须归成 ``[id]``，
   静态段必须原样保留（``/admin/model-eval`` 不能被误伤）。
3. **值域校验与聚合**（``validate_sample`` / ``record_samples`` / ``summarize``）：
   非法条目逐条丢弃；p75 按最近秩法取到正确的那个样本。

走内存 SQLite：仓库的分位数查询刻意只用乘法与比较（不用 percentile_cont），
PG 与 SQLite 行为一致。
"""

from __future__ import annotations

import math

import pytest

import app.models.web_vitals  # noqa: F401 - 注册 Base.metadata
from app.services import web_vitals_service as service

# ── 阈值判定 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("metric", "value", "expected"),
    [
        ("LCP", 0.0, "good"),
        ("LCP", 2500.0, "good"),  # 等于 good 上界仍是 good
        ("LCP", 2500.1, "needs-improvement"),
        ("LCP", 4000.0, "needs-improvement"),  # 等于 needs-improvement 上界
        ("LCP", 4000.1, "poor"),
        ("INP", 200.0, "good"),
        ("INP", 200.5, "needs-improvement"),
        ("INP", 500.0, "needs-improvement"),
        ("INP", 501.0, "poor"),
        ("CLS", 0.1, "good"),
        ("CLS", 0.11, "needs-improvement"),
        ("CLS", 0.25, "needs-improvement"),
        ("CLS", 0.26, "poor"),
        ("FCP", 1800.0, "good"),
        ("FCP", 3001.0, "poor"),
        ("TTFB", 800.0, "good"),
        ("TTFB", 1801.0, "poor"),
    ],
)
def test_classify_metric_boundaries(metric: str, value: float, expected: str):
    assert service.classify_metric(metric, value) == expected


# ── 路径归一 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("/", "/"),
        ("", "/"),
        ("/trending", "/trending"),
        ("/trending/", "/trending"),
        ("/topics/123", "/topics/[id]"),
        ("/contents/5/reader", "/contents/[id]/reader"),
        ("/topics/123/related/456", "/topics/[id]/related/[id]"),
        ("/admin/model-eval", "/admin/model-eval"),
        ("/stats/jobs", "/stats/jobs"),
        ("/topics/abc", "/topics/abc"),
        (
            "/items/3f2504e0-4f89-41d3-9a0c-0305e82c3301",
            "/items/[id]",
        ),
        ("/topics/123?tab=related", "/topics/[id]"),
        ("/topics/123#frag", "/topics/[id]"),
        ("topics/123", "/topics/[id]"),
    ],
)
def test_normalize_route_path(raw: str, expected: str):
    assert service.normalize_route_path(raw) == expected


# ── 值域校验 ────────────────────────────────────────────────────────


def test_validate_sample_accepts_normal_sample():
    sample = service.validate_sample("LCP", 1200.0, "/topics/7", "navigate", "desktop")
    assert sample is not None
    assert sample.path == "/topics/[id]"
    assert sample.rating == "good"
    assert sample.navigation_type == "navigate"
    assert sample.device_class == "desktop"


@pytest.mark.parametrize(
    ("metric", "value"),
    [
        ("XYZ", 100.0),  # 不在白名单
        ("LCP", -1.0),  # 负值
        ("LCP", math.inf),  # 无穷
        ("LCP", math.nan),  # NaN
        ("LCP", 60_001.0),  # 超过时间指标上界
        ("CLS", 101.0),  # 超过 CLS 上界
    ],
)
def test_validate_sample_rejects_invalid(metric: str, value: float):
    assert service.validate_sample(metric, value, "/", "navigate", "desktop") is None


def test_validate_sample_falls_back_on_unknown_enums():
    sample = service.validate_sample("LCP", 100.0, "/", "weird-nav", "toaster")
    assert sample is not None
    assert sample.navigation_type == "navigate"
    assert sample.device_class == "unknown"


def test_validate_sample_rejects_overlong_path():
    long_path = "/" + "a" * 300
    assert service.validate_sample("LCP", 100.0, long_path, "navigate", "desktop") is None


# ── 写入与聚合 ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_record_samples_drops_invalid_entries(db):
    accepted, rejected = await service.record_samples(
        db,
        [
            ("LCP", 1200.0, "/topics/1", "navigate", "desktop"),
            ("NOPE", 1200.0, "/", "navigate", "desktop"),
            ("LCP", 999_999.0, "/", "navigate", "desktop"),
        ],
        user_id=None,
    )
    assert accepted == 1
    assert rejected == 2
    await db.commit()


@pytest.mark.asyncio
async def test_summarize_computes_nearest_rank_p75(db):
    # 四个样本，p75 的最近秩 = 第 3 个（ceil(0.75 × 4) = 3）
    for value in (1000.0, 2000.0, 3000.0, 4000.0):
        await service.record_samples(db, [("LCP", value, "/", "navigate", "desktop")])
    await db.commit()

    summary = await service.summarize(db, hours=24, navigation_type="navigate")
    lcp = next(item for item in summary["metrics"] if item["metric"] == "LCP")
    assert lcp["p75"] == 3000.0
    assert lcp["p50"] == 2000.0
    assert lcp["sample_count"] == 4
    assert lcp["rating"] == "needs-improvement"
    assert summary["sample_count"] == 4


@pytest.mark.asyncio
async def test_summarize_separates_navigation_types(db):
    await service.record_samples(db, [("LCP", 1000.0, "/", "navigate", "desktop")])
    await service.record_samples(db, [("LCP", 5000.0, "/", "soft-navigation", "desktop")])
    await db.commit()

    navigate_only = await service.summarize(db, hours=24, navigation_type="navigate")
    assert navigate_only["sample_count"] == 1
    assert navigate_only["metrics"][0]["p75"] == 1000.0

    soft_only = await service.summarize(db, hours=24, navigation_type="soft-navigation")
    assert soft_only["sample_count"] == 1
    assert soft_only["metrics"][0]["p75"] == 5000.0
    assert soft_only["metrics"][0]["rating"] == "poor"

    everything = await service.summarize(db, hours=24, navigation_type="all")
    assert everything["sample_count"] == 2


@pytest.mark.asyncio
async def test_summarize_breaks_down_by_normalized_path(db):
    await service.record_samples(db, [("LCP", 1000.0, "/topics/1", "navigate", "desktop")])
    await service.record_samples(db, [("LCP", 1200.0, "/topics/2", "navigate", "desktop")])
    await service.record_samples(db, [("LCP", 900.0, "/trending", "navigate", "desktop")])
    await db.commit()

    summary = await service.summarize(db, hours=24, navigation_type="navigate")
    paths = {route["path"] for route in summary["routes"]}
    assert paths == {"/topics/[id]", "/trending"}
    # 归一后两条 /topics/[id] 样本合并成一组，不是两条
    topic_route = next(route for route in summary["routes"] if route["path"] == "/topics/[id]")
    assert topic_route["sample_count"] == 2


@pytest.mark.asyncio
async def test_summarize_empty_window(db):
    summary = await service.summarize(db, hours=24, navigation_type="navigate")
    assert summary["sample_count"] == 0
    assert summary["metrics"] == []
    assert summary["routes"] == []


@pytest.mark.asyncio
async def test_cleanup_old_samples_removes_only_expired(db):
    await service.record_samples(db, [("LCP", 1000.0, "/", "navigate", "desktop")])
    await db.commit()

    removed = await service.cleanup_old_samples(db)
    await db.commit()
    assert removed == 0

    # 用「未来一天」当 cutoff，模拟超期样本
    from datetime import UTC, datetime, timedelta

    from app.repositories.web_vitals_repo import WebVitalsRepository

    removed = await WebVitalsRepository(db).delete_older_than(datetime.now(UTC) + timedelta(days=1))
    await db.commit()
    assert removed == 1
