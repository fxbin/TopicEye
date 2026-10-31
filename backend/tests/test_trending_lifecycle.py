"""趋势生命周期阶段标注（issue #173）测试。

四部分：
1. classify_topic_stage 决策树单测——四分支 + 全部边界
   （单点 / 恰好 5 天 / 恰好 30% / 恰好前 10 / 持平 / 连续 2 点 /
   同日多平台折叠 / 跨日名次波动 / 乱序输入 / 空序列）。
2. build_topic_stage_map 归一测试——精确同题与高相似变体共存时两条
   路径同簇（Verifier 阻断 1 回归）、共振口径相似匹配、无关标题、
   SYNC_EXCLUDED 信源排除、空窗口、标题 strip、坏快照容错。
3. 窗口语义——恰好 today-7 边界日参与、today-8 排除；窗口常量与
   快照保留期挂钩。
4. GET /api/v1/trending 集成测试——响应含 stage/stage_reason、
   无窗口数据条目为 null、既有字段与排序不回归、缓存载荷带新字段、
   空窗口行为、坏快照行不把列表打成 500。
"""

from __future__ import annotations

from datetime import date, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import trending as trending_api
from app.core.database import Base
from app.models.trending import TrendingCategory, TrendingItem, TrendingSnapshot, TrendingSource
from app.services.trending_cache import invalidate_trending_cache
from app.services.trending_lifecycle import (
    STAGE_WINDOW_DAYS,
    TopicPoint,
    TrendStage,
    build_topic_stage_map,
    classify_topic_stage,
    compute_trending_item_stages,
)
from app.services.trending_snapshot import SNAPSHOT_RETENTION_DAYS

TODAY = date.today()


def _days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


# ── 1. 决策树单测 ─────────────────────────────────────────────────────


def test_empty_points_returns_none():
    assert classify_topic_stage([]) is None


def test_evergreen_at_exactly_five_days():
    points = [TopicPoint(date=_days_ago(i), rank=3) for i in range(5)]  # 恰好 5 天
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.EVERGREEN
    assert info.stage_reason == "在榜 5 天 · 最新排名 3"


def test_evergreen_takes_precedence_over_declining_tail():
    # 6 天在榜且尾部回落，常青优先
    points = [TopicPoint(date=_days_ago(i), rank=2) for i in range(5, 0, -1)]
    points.append(TopicPoint(date=TODAY, rank=18))
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.EVERGREEN
    assert "在榜 6 天" in info.stage_reason


def test_peaking_at_exactly_thirty_percent_rise():
    # 前一日 10 → 今日 7：恰好 30%（含等号）→ 爆发
    points = [TopicPoint(date=_days_ago(1), rank=10), TopicPoint(date=TODAY, rank=7)]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.PEAKING
    assert info.stage_reason == "排名较上一在榜日上升 30% · 最新排名 7"


def test_peaking_rise_reason_carries_data():
    # 20 → 11 = 45%
    points = [TopicPoint(date=_days_ago(1), rank=20), TopicPoint(date=TODAY, rank=11)]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.PEAKING
    assert info.stage_reason == "排名较上一在榜日上升 45% · 最新排名 11"


def test_peaking_at_exactly_top_ten_boundary():
    # 恰好第 10 名（≤10 含等号）且无 ≥30% 上升 → 爆发
    points = [
        TopicPoint(date=_days_ago(1), rank=11),
        TopicPoint(date=TODAY, rank=10),  # (11-10)/11 ≈ 9% < 30%
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.PEAKING
    assert info.stage_reason == "进入前 10 · 最新排名 10"


def test_peaking_single_point_inside_top_ten():
    # 单快照点：无前一日可比，仅凭「进入前 10」判爆发
    info = classify_topic_stage([TopicPoint(date=TODAY, rank=5)])
    assert info is not None and info.stage is TrendStage.PEAKING
    assert info.stage_reason == "进入前 10 · 最新排名 5"


def test_ferment_single_point_outside_top_ten():
    info = classify_topic_stage([TopicPoint(date=TODAY, rank=30)])
    assert info is not None and info.stage is TrendStage.FERMENT
    assert info.stage_reason == "在榜 1 天 · 最新排名 30"


def test_ferment_when_rank_flat():
    # 排名持平：0% <30% 不爆发、不回落 → 发酵
    points = [
        TopicPoint(date=_days_ago(2), rank=12),
        TopicPoint(date=_days_ago(1), rank=12),
        TopicPoint(date=TODAY, rank=12),
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.FERMENT
    assert "最新排名 12" in info.stage_reason


def test_declining_two_points_minimal_case():
    # 连续 2 点回落（最小情形）：5 → 15，且 15 > 10 不满足爆发
    points = [TopicPoint(date=_days_ago(1), rank=5), TopicPoint(date=TODAY, rank=15)]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.DECLINING
    assert info.stage_reason == "排名回落 5 → 15 · 在榜 2 天"


def test_declining_longer_streak_still_declining():
    points = [
        TopicPoint(date=_days_ago(2), rank=5),
        TopicPoint(date=_days_ago(1), rank=8),
        TopicPoint(date=TODAY, rank=15),
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.DECLINING


def test_cross_day_rank_fluctuation_judged_by_latest_transition():
    # 跨日波动 5 → 15 → 8：最近一次转变是上升（46.7% ≥30%）→ 爆发而非回落
    points = [
        TopicPoint(date=_days_ago(2), rank=5),
        TopicPoint(date=_days_ago(1), rank=15),
        TopicPoint(date=TODAY, rank=8),
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.PEAKING
    assert "上升 47%" in info.stage_reason  # round((15-8)/15*100) = 47


def test_same_day_multi_platform_collapses_to_best_rank():
    # 同日两平台 3 / 25 → 取最好名次 3；次日 12：3 → 12 回落（若取 25 会误判爆发）
    points = [
        TopicPoint(date=_days_ago(1), rank=3),
        TopicPoint(date=_days_ago(1), rank=25),
        TopicPoint(date=TODAY, rank=12),
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.DECLINING
    assert info.stage_reason == "排名回落 3 → 12 · 在榜 2 天"


def test_same_day_collapse_can_lift_into_peaking():
    # 同日 18 / 9 → 取最好 9；次日 3：9 → 3 上升 66% → 爆发（同日折叠取最好名次参与比较）
    points = [
        TopicPoint(date=_days_ago(1), rank=18),
        TopicPoint(date=_days_ago(1), rank=9),
        TopicPoint(date=TODAY, rank=3),
    ]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.PEAKING


def test_unordered_input_dates_are_sorted():
    shuffled = [
        TopicPoint(date=TODAY, rank=15),
        TopicPoint(date=_days_ago(1), rank=5),
    ]
    info = classify_topic_stage(shuffled)
    assert info is not None and info.stage is TrendStage.DECLINING


def test_four_days_mid_course_falls_to_ferment():
    # 4 天、无上升、11 名开外、最近一次转变持平 → 发酵
    points = [TopicPoint(date=_days_ago(i), rank=20) for i in range(4)]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.FERMENT
    assert "在榜 4 天" in info.stage_reason


def test_non_consecutive_days_still_count_toward_evergreen():
    # 在榜天数为窗口内不同日期数（非连续）：隔天在榜累计 5 天 → 常青
    days = [8 - 2 * i for i in range(5)]  # 8,6,4,2,0 天前
    points = [TopicPoint(date=_days_ago(d), rank=6) for d in days]
    info = classify_topic_stage(points)
    assert info is not None and info.stage is TrendStage.EVERGREEN
    assert "在榜 5 天" in info.stage_reason


# ── 2. 归一（build_topic_stage_map）单测 ──────────────────────────────


class _FakeSnapshot:
    """TrendingSnapshot 的鸭子类型替身：只暴露归一所需字段。"""

    def __init__(self, snapshot_date: date, source: str, items: list[dict]):
        self.snapshot_date = snapshot_date
        self.source = source
        self.items = items


def test_exact_title_match_produces_stage():
    snaps = [
        _FakeSnapshot(_days_ago(1), "weibo", [{"title": "AI 大模型发布会", "rank": 10, "hot_value": 1}]),
        _FakeSnapshot(TODAY, "weibo", [{"title": "AI 大模型发布会", "rank": 7, "hot_value": 2}]),
    ]
    stage_map = build_topic_stage_map(["AI 大模型发布会"], snaps)
    info = stage_map["AI 大模型发布会"]
    assert info is not None and info.stage is TrendStage.PEAKING


def test_resonance_similarity_matches_variant_titles():
    # 共振分析口径：关键词相似度 ≥ SIM_THRESHOLD 即同一 topic
    snaps = [
        _FakeSnapshot(
            _days_ago(1),
            "baidu",
            [{"title": "AI 大模型发布会现场直击", "rank": 20, "hot_value": 5}],
        ),
        _FakeSnapshot(
            TODAY,
            "zhihu",
            [{"title": "AI 大模型发布会现场直击", "rank": 11, "hot_value": 6}],
        ),
    ]
    stage_map = build_topic_stage_map(["AI 大模型发布会"], snaps)
    info = stage_map["AI 大模型发布会"]
    assert info is not None and info.stage is TrendStage.PEAKING
    assert "上升 45%" in info.stage_reason


def test_unrelated_title_has_null_stage():
    snaps = [_FakeSnapshot(TODAY, "weibo", [{"title": "欧冠决赛裁判争议", "rank": 1, "hot_value": 9}])]
    stage_map = build_topic_stage_map(["AI 大模型发布会"], snaps)
    assert stage_map["AI 大模型发布会"] is None


def test_sync_excluded_sources_are_ignored():
    snaps = [
        _FakeSnapshot(_days_ago(i), "heiyan", [{"title": "某本网文小说", "rank": 1, "hot_value": 1}]) for i in range(5)
    ]
    stage_map = build_topic_stage_map(["某本网文小说"], snaps)
    assert stage_map["某本网文小说"] is None


def test_empty_window_yields_all_null():
    stage_map = build_topic_stage_map(["AI 大模型发布会", "别的标题"], [])
    assert stage_map == {"AI 大模型发布会": None, "别的标题": None}


def test_titles_are_stripped_as_keys():
    snaps = [_FakeSnapshot(TODAY, "weibo", [{"title": "AI 大模型发布会", "rank": 1, "hot_value": 1}])]
    stage_map = build_topic_stage_map(["  AI 大模型发布会  "], snaps)
    assert stage_map["AI 大模型发布会"] is not None


def test_similarity_match_merges_days_across_variant_titles():
    # 相似标题跨日合并，累计 5 天 → 常青（归一口径参与天数累计）
    snaps = [
        _FakeSnapshot(
            _days_ago(i),
            "weibo",
            [{"title": f"量子芯片量产最新进展（第{i}天）", "rank": 4, "hot_value": 1}],
        )
        for i in range(5)
    ]
    stage_map = build_topic_stage_map(["量子芯片量产突破"], snaps)
    info = stage_map["量子芯片量产突破"]
    assert info is not None and info.stage is TrendStage.EVERGREEN


def test_empty_snapshot_title_entries_are_skipped():
    snaps = [_FakeSnapshot(TODAY, "weibo", [{"title": "   ", "rank": 1, "hot_value": 1}])]
    stage_map = build_topic_stage_map(["任意标题"], snaps)
    assert stage_map["任意标题"] is None


def test_exact_and_variant_titles_merge_into_same_cluster():
    """回归（Verifier 阻断 1）：精确同题与高相似变体共存时，两条路径必须同簇。

    前 4 天快照与实时标题精确同题，今日快照是高相似变体（sim 0.9）。
    旧实现精确命中走捷径、漏并今日变体，拿陈旧 rank 判成 peaking；
    统一相似扩展后，精确路径与模糊路径得到完全相同的结果。
    """
    snaps = [
        _FakeSnapshot(_days_ago(offset), "weibo", [{"title": "量子芯片量产突破", "rank": 8, "hot_value": 1}])
        for offset in range(4, 0, -1)
    ] + [_FakeSnapshot(TODAY, "zhihu", [{"title": "量子芯片量产最新进展", "rank": 3, "hot_value": 2}])]

    exact_path = build_topic_stage_map(["量子芯片量产突破"], snaps)["量子芯片量产突破"]
    fuzzy_path = build_topic_stage_map(["量子芯片量产最新进展"], snaps)["量子芯片量产最新进展"]

    # 两条路径同一共振簇：合并全部 5 天观测，最新排名来自今日变体
    assert exact_path is not None and exact_path.stage is TrendStage.EVERGREEN
    assert exact_path.stage_reason == "在榜 5 天 · 最新排名 3"
    assert fuzzy_path is not None and fuzzy_path.stage is TrendStage.EVERGREEN
    assert fuzzy_path.stage_reason == "在榜 5 天 · 最新排名 3"


def test_malformed_snapshot_items_are_skipped_not_fatal():
    """坏快照（items 非列表 / 条目非 dict / rank 非数值）跳过并降级，不抛异常。

    两个话题标题刻意选为语义无关（关键词无交集），避免共振口径把
    坏话题 live 标题相似匹配到好话题的观测上。
    """
    snaps = [
        _FakeSnapshot(
            TODAY,
            "weibo",
            [
                "裸字符串条目",
                {"title": "烂尾楼盘维权", "rank": "第一"},
                {"title": "", "rank": 2},
                {"title": "量子芯片量产突破", "rank": 12, "hot_value": 3},
            ],
        ),
        _FakeSnapshot(_days_ago(1), "weibo", [{"title": "量子芯片量产突破", "rank": 12, "hot_value": 2}]),
        _FakeSnapshot(TODAY, "baidu", "快照条目不是列表"),
    ]
    stage_map = build_topic_stage_map(["烂尾楼盘维权", "量子芯片量产突破"], snaps)
    # 唯一观测损坏 → 无窗口数据 → null
    assert stage_map["烂尾楼盘维权"] is None
    # 同行其余好条目不受影响：2 天 rank 12 持平 → 发酵
    good = stage_map["量子芯片量产突破"]
    assert good is not None and good.stage is TrendStage.FERMENT
    assert good.stage_reason == "在榜 2 天 · 最新排名 12"


# ── 3. 窗口语义 ───────────────────────────────────────────────────────


def test_stage_window_days_tied_to_snapshot_retention():
    """窗口常量挂钩快照保留期，两边不各自维护 7 天数字。"""
    assert STAGE_WINDOW_DAYS == SNAPSHOT_RETENTION_DAYS


@pytest.mark.asyncio
async def test_compute_stages_window_boundary_includes_exactly_day_seven(db):
    """窗口边界：恰好 today-STAGE_WINDOW_DAYS 当日的快照参与判定，再早一天排除。"""

    async def _add_snapshot(snapshot_date: date, title: str) -> None:
        db.add(
            TrendingSnapshot(
                snapshot_date=snapshot_date,
                snapshot_hour=22,
                source=TrendingSource.WEIBO,
                category="hot",
                items=[{"title": title, "rank": 30, "hot_value": 1}],
                total_count=1,
            )
        )

    # 两个话题标题刻意语义无关，避免共振口径把窗外标题匹配到边界标题
    await _add_snapshot(_days_ago(STAGE_WINDOW_DAYS), "量子芯片量产突破")
    await _add_snapshot(_days_ago(STAGE_WINDOW_DAYS + 1), "欧冠决赛裁判争议")
    await db.flush()

    stage_map = await compute_trending_item_stages(db, ["量子芯片量产突破", "欧冠决赛裁判争议"])

    # 边界日（today-7，含等号）参与：单点 rank 30 → 发酵
    boundary = stage_map["量子芯片量产突破"]
    assert boundary is not None and boundary.stage is TrendStage.FERMENT
    assert boundary.stage_reason == "在榜 1 天 · 最新排名 30"
    # 窗外一天（today-8）不参与 → null
    assert stage_map["欧冠决赛裁判争议"] is None


# ── 4. API 集成测试 ───────────────────────────────────────────────────


async def _seed_trending_fixture(session_factory) -> None:
    async with session_factory() as db:
        db.add_all(
            [
                TrendingItem(
                    id=1,
                    source=TrendingSource.WEIBO,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="AI 大模型发布会",
                    url="https://example.com/t/ai",
                    hot_value=1000,
                    hot_value_raw="1000",
                    trend="up",
                    batch_id="stage-test",
                ),
                TrendingItem(
                    id=2,
                    source=TrendingSource.BAIDU,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="新机型首发破纪录",
                    url="https://example.com/t/phone",
                    hot_value=900,
                    hot_value_raw="900",
                    trend="up",
                    batch_id="stage-test",
                ),
                TrendingItem(
                    id=3,
                    source=TrendingSource.ZHIHU,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="欧冠决赛裁判争议",
                    url="https://example.com/t/final",
                    hot_value=800,
                    hot_value_raw="800",
                    trend="down",
                    batch_id="stage-test",
                ),
                TrendingItem(
                    id=4,
                    source=TrendingSource.TOUTIAO,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="小众纪录片走红",
                    url="https://example.com/t/doc",
                    hot_value=700,
                    hot_value_raw="700",
                    trend="new",
                    batch_id="stage-test",
                ),
                TrendingItem(
                    id=5,
                    source=TrendingSource.KR36,
                    category=TrendingCategory.TECH,
                    rank=1,
                    title="完全无快照的话题",
                    url="https://example.com/t/none",
                    hot_value=600,
                    hot_value_raw="600",
                    batch_id="stage-test",
                ),
                TrendingItem(
                    id=6,
                    source=TrendingSource.ITHOME,
                    category=TrendingCategory.TECH,
                    rank=1,
                    title="老话题回顾",
                    url="https://example.com/t/old",
                    hot_value=500,
                    hot_value_raw="500",
                    batch_id="stage-test",
                ),
            ]
        )
        # 快照：标题与实时条目精确同题，保证匹配确定
        db.add_all(
            [
                # 常青：连续 5 天在榜
                TrendingSnapshot(
                    snapshot_date=_days_ago(offset),
                    snapshot_hour=22,
                    source=TrendingSource.WEIBO,
                    category="hot",
                    items=[{"title": "AI 大模型发布会", "rank": 3, "hot_value": 1000}],
                    total_count=1,
                )
                for offset in range(5)
            ]
            + [
                # 爆发：20 → 11（45%）
                TrendingSnapshot(
                    snapshot_date=_days_ago(1),
                    snapshot_hour=22,
                    source=TrendingSource.BAIDU,
                    category="hot",
                    items=[{"title": "新机型首发破纪录", "rank": 20, "hot_value": 900}],
                    total_count=1,
                ),
                TrendingSnapshot(
                    snapshot_date=TODAY,
                    snapshot_hour=22,
                    source=TrendingSource.BAIDU,
                    category="hot",
                    items=[{"title": "新机型首发破纪录", "rank": 11, "hot_value": 950}],
                    total_count=1,
                ),
                # 回落：5 → 15
                TrendingSnapshot(
                    snapshot_date=_days_ago(1),
                    snapshot_hour=22,
                    source=TrendingSource.ZHIHU,
                    category="hot",
                    items=[{"title": "欧冠决赛裁判争议", "rank": 5, "hot_value": 800}],
                    total_count=1,
                ),
                TrendingSnapshot(
                    snapshot_date=TODAY,
                    snapshot_hour=22,
                    source=TrendingSource.ZHIHU,
                    category="hot",
                    items=[{"title": "欧冠决赛裁判争议", "rank": 15, "hot_value": 700}],
                    total_count=1,
                ),
                # 发酵：今日新上榜且 10 名开外
                TrendingSnapshot(
                    snapshot_date=TODAY,
                    snapshot_hour=22,
                    source=TrendingSource.TOUTIAO,
                    category="hot",
                    items=[{"title": "小众纪录片走红", "rank": 30, "hot_value": 700}],
                    total_count=1,
                ),
                # 窗口外：12 天前的快照不参与判定
                TrendingSnapshot(
                    snapshot_date=_days_ago(12),
                    snapshot_hour=22,
                    source=TrendingSource.ITHOME,
                    category="tech",
                    items=[{"title": "老话题回顾", "rank": 1, "hot_value": 500}],
                    total_count=1,
                ),
            ]
        )
        await db.commit()


@pytest_asyncio.fixture
async def trending_stage_app(monkeypatch):
    """挂载 trending 路由的测试 app，数据落在内存 SQLite。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    invalidate_trending_cache()
    monkeypatch.setattr(trending_api, "async_session", session_factory)
    await _seed_trending_fixture(session_factory)

    app = FastAPI()
    app.include_router(trending_api.router)
    yield app

    invalidate_trending_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_trending_list_returns_stage_fields(trending_stage_app):
    transport = httpx.ASGITransport(app=trending_stage_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/trending", params={"limit": 10})
    assert resp.status_code == 200
    assert resp.headers["x-trending-cache"].startswith("MISS")

    items = resp.json()
    by_title = {item["title"]: item for item in items}

    # 既有字段不回归
    for field in (
        "id",
        "source",
        "category",
        "rank",
        "title",
        "url",
        "hot_value",
        "hot_value_raw",
        "trend",
        "cover_url",
        "extra",
    ):
        assert all(field in item for item in items), field

    evergreen = by_title["AI 大模型发布会"]
    assert evergreen["stage"] == "evergreen"
    assert evergreen["stage_reason"] == "在榜 5 天 · 最新排名 3"

    peaking = by_title["新机型首发破纪录"]
    assert peaking["stage"] == "peaking"
    assert peaking["stage_reason"] == "排名较上一在榜日上升 45% · 最新排名 11"

    declining = by_title["欧冠决赛裁判争议"]
    assert declining["stage"] == "declining"
    assert declining["stage_reason"] == "排名回落 5 → 15 · 在榜 2 天"

    ferment = by_title["小众纪录片走红"]
    assert ferment["stage"] == "ferment"
    assert ferment["stage_reason"] == "在榜 1 天 · 最新排名 30"

    # 无窗口数据（窗口内无该 topic 记录）→ null
    assert by_title["完全无快照的话题"]["stage"] is None
    assert by_title["完全无快照的话题"]["stage_reason"] is None
    # 窗口外快照不算数 → null
    assert by_title["老话题回顾"]["stage"] is None

    # 排序不动：仍按 source, rank
    assert [item["source"] for item in items] == sorted(item["source"] for item in items)


@pytest.mark.asyncio
async def test_trending_list_cache_carries_stage_fields(trending_stage_app):
    transport = httpx.ASGITransport(app=trending_stage_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.get("/trending", params={"limit": 10})
        assert first.headers["x-trending-cache"].startswith("MISS")
        second = await client.get("/trending", params={"limit": 10})
        assert second.headers["x-trending-cache"].startswith("HIT")

    first_items = {i["title"]: i for i in first.json()}
    second_items = {i["title"]: i for i in second.json()}
    assert first_items["AI 大模型发布会"]["stage"] == "evergreen"
    assert second_items["AI 大模型发布会"]["stage"] == "evergreen"
    assert second_items["完全无快照的话题"]["stage"] is None


@pytest.mark.asyncio
async def test_trending_list_empty_window_yields_null_stages(monkeypatch):
    """空窗口（无任何快照）：所有条目 stage/stage_reason 均为 null。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    invalidate_trending_cache()
    monkeypatch.setattr(trending_api, "async_session", session_factory)
    async with session_factory() as db:
        db.add(
            TrendingItem(
                source=TrendingSource.WEIBO,
                category=TrendingCategory.HOT,
                rank=1,
                title="没有快照的条目",
                url="https://example.com/t/x",
                hot_value=100,
                hot_value_raw="100",
                batch_id="empty-window",
            )
        )
        await db.commit()

    app = FastAPI()
    app.include_router(trending_api.router)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/trending", params={"limit": 5})
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["stage"] is None
        assert items[0]["stage_reason"] is None
        assert items[0]["title"] == "没有快照的条目"
    finally:
        invalidate_trending_cache()
        await engine.dispose()


@pytest.mark.asyncio
async def test_trending_list_survives_corrupt_snapshot_rows(monkeypatch):
    """坏快照行（Verifier 顺手修 2）：GET /trending 仍 200，坏条目 stage=null，好条目不受影响。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    invalidate_trending_cache()
    monkeypatch.setattr(trending_api, "async_session", session_factory)
    async with session_factory() as db:
        db.add_all(
            [
                TrendingItem(
                    id=1,
                    source=TrendingSource.WEIBO,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="烂尾楼盘维权",
                    url="https://example.com/t/bad",
                    hot_value=100,
                    hot_value_raw="100",
                    batch_id="corrupt-test",
                ),
                TrendingItem(
                    id=2,
                    source=TrendingSource.BAIDU,
                    category=TrendingCategory.HOT,
                    rank=1,
                    title="量子芯片量产突破",
                    url="https://example.com/t/good",
                    hot_value=200,
                    hot_value_raw="200",
                    batch_id="corrupt-test",
                ),
            ]
        )
        db.add_all(
            [
                # 坏行：条目含非 dict 与非数值 rank，该话题的观测全部作废
                # （两个话题标题刻意语义无关，避免共振口径跨匹配）
                TrendingSnapshot(
                    snapshot_date=_days_ago(1),
                    snapshot_hour=22,
                    source=TrendingSource.WEIBO,
                    category="hot",
                    items=["裸字符串", {"title": "烂尾楼盘维权", "rank": "第一", "hot_value": 1}],
                    total_count=2,
                ),
                # 好行：20 → 11（45%）→ 爆发
                TrendingSnapshot(
                    snapshot_date=_days_ago(1),
                    snapshot_hour=22,
                    source=TrendingSource.BAIDU,
                    category="hot",
                    items=[{"title": "量子芯片量产突破", "rank": 20, "hot_value": 200}],
                    total_count=1,
                ),
                TrendingSnapshot(
                    snapshot_date=TODAY,
                    snapshot_hour=22,
                    source=TrendingSource.BAIDU,
                    category="hot",
                    items=[{"title": "量子芯片量产突破", "rank": 11, "hot_value": 210}],
                    total_count=1,
                ),
            ]
        )
        await db.commit()

    app = FastAPI()
    app.include_router(trending_api.router)
    transport = httpx.ASGITransport(app=app)
    try:
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/trending", params={"limit": 5})
        assert resp.status_code == 200
        by_title = {item["title"]: item for item in resp.json()}
        assert by_title["烂尾楼盘维权"]["stage"] is None
        assert by_title["烂尾楼盘维权"]["stage_reason"] is None
        assert by_title["量子芯片量产突破"]["stage"] == "peaking"
    finally:
        invalidate_trending_cache()
        await engine.dispose()
