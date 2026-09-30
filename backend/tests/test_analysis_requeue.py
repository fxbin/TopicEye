"""降级内容补分析（requeue）与预算豁免/余量门控的回归测试（#90）。

覆盖：
- repo.reset_local_fallback_for_reanalysis：资格（最新分析是 local_fallback）、
  cooldown、skip_analysis、max_age、limit 最旧优先、reset 字段语义；
- requeue_local_fallback_content：预算余量门控；
- budget_guard.budget_headroom_ok：全关、余量足、不足、fail-closed；
- 预算豁免场景（daily_report 等）超限仍放行。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType
from app.repositories.content_repo import ContentRepo
from app.services.analysis_requeue import requeue_local_fallback_content
from app.services.llm.budget_guard import (
    LlmBudgetExceededError,
    budget_headroom_ok,
    ensure_llm_budget,
)


def _set_budget(monkeypatch, minute: int, hour: int, day: int) -> None:
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_MINUTE", minute)
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_HOUR", hour)
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_DAY", day)


def _content(
    item_id: int,
    *,
    now: datetime,
    updated_at: datetime | None = None,
    created_at: datetime | None = None,
    skip_analysis: bool = False,
    status: ContentStatus = ContentStatus.ANALYZED,
) -> ContentItem:
    return ContentItem(
        id=item_id,
        title=f"降级样本 {item_id}",
        url=f"https://example.com/fallback-{item_id}",
        source_id=1,
        source_name="降级测试信源",
        source_type="RSS",
        category="AI",
        status=status,
        skip_analysis=skip_analysis,
        crawled_at=now,
        published_at=now,
        created_at=created_at or now,
        updated_at=updated_at or now - timedelta(minutes=120),
    )


async def _seed(db, now: datetime) -> None:
    db.add(
        Source(
            id=1,
            name="降级测试信源",
            source_type=SourceType.RSS,
            url="https://example.com/fallback.xml",
            category="AI",
            status=SourceStatus.ACTIVE,
            enabled=True,
            weight=3,
        )
    )
    # id=1：最新分析是 local_fallback，超过 cooldown —— 应被回收
    db.add(_content(1, now=now))
    # id=2：最新分析是真实 LLM（fallback 之后又真实分析过）—— 不动
    db.add(_content(2, now=now))
    # id=3：fallback 但 cooldown 内（updated_at 刚刷新）—— 不动
    db.add(_content(3, now=now, updated_at=now - timedelta(minutes=5)))
    # id=4：fallback 但显式 skip_analysis —— 不动
    db.add(_content(4, now=now, skip_analysis=True))
    # id=5：fallback 但超过 max_age_days —— 不动
    db.add(_content(5, now=now, created_at=now - timedelta(days=10)))

    analyses = [
        # id=1：一条真实分析（旧）+ 一条 fallback（新）→ 最新是 fallback
        AiAnalysis(id=101, content_id=1, curation_score=80, created_at=now - timedelta(hours=3)),
        AiAnalysis(
            id=102,
            content_id=1,
            curation_score=62,
            summary_source="local_fallback",
            created_at=now - timedelta(hours=2),
        ),
        # id=2：fallback（旧）+ 真实分析（新）→ 最新是真实
        AiAnalysis(
            id=103,
            content_id=2,
            curation_score=62,
            summary_source="local_fallback",
            created_at=now - timedelta(hours=3),
        ),
        AiAnalysis(id=104, content_id=2, curation_score=85, created_at=now - timedelta(hours=1)),
        # id=3/4/5：最新分析均为 fallback
        AiAnalysis(
            id=105,
            content_id=3,
            curation_score=62,
            summary_source="local_fallback",
            created_at=now - timedelta(minutes=10),
        ),
        AiAnalysis(
            id=106,
            content_id=4,
            curation_score=62,
            summary_source="local_fallback",
            created_at=now - timedelta(hours=2),
        ),
        AiAnalysis(
            id=107,
            content_id=5,
            curation_score=62,
            summary_source="local_fallback",
            created_at=now - timedelta(days=9),
        ),
    ]
    db.add_all(analyses)
    await db.commit()


@pytest.mark.asyncio
async def test_reset_local_fallback_eligibility_and_fields():
    """只有「最新分析是 fallback 且过冷却」的内容被回收，reset 字段语义正确。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        await _seed(db, now)
        repo = ContentRepo(db)
        count = await repo.reset_local_fallback_for_reanalysis(limit=10, cooldown_minutes=60, max_age_days=7)
        assert count == 1, "只有 id=1 同时满足最新分析为 fallback、过冷却、未跳过、未过期"

        item1 = await db.get(ContentItem, 1)
        assert item1 is not None
        assert item1.status == ContentStatus.PENDING
        assert item1.analysis_attempts == 0
        assert item1.analysis_next_retry_at is None
        assert item1.analysis_claim_token is None
        assert item1.analysis_lease_expires_at is None

        for unchanged_id in (2, 3, 4, 5):
            item = await db.get(ContentItem, unchanged_id)
            assert item is not None
            assert item.status == ContentStatus.ANALYZED, f"id={unchanged_id} 不应被回收"

    await engine.dispose()


@pytest.mark.asyncio
async def test_reset_respects_limit_oldest_first():
    """limit 限速且最旧优先。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="信源",
                source_type=SourceType.RSS,
                url="https://example.com/x.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        # 三条 fallback 内容，created_at 递减（id=10 最旧）
        for item_id, age_hours in ((10, 6), (11, 4), (12, 2)):
            db.add(
                _content(
                    item_id,
                    now=now,
                    created_at=now - timedelta(hours=age_hours),
                    updated_at=now - timedelta(hours=age_hours),
                )
            )
            db.add(
                AiAnalysis(
                    id=200 + item_id,
                    content_id=item_id,
                    curation_score=62,
                    summary_source="local_fallback",
                    created_at=now - timedelta(hours=age_hours),
                )
            )
        await db.commit()

        repo = ContentRepo(db)
        count = await repo.reset_local_fallback_for_reanalysis(limit=1, cooldown_minutes=60)
        assert count == 1
        pending_ids = [
            int(row[0])
            for row in (
                await db.execute(select(ContentItem.id).where(ContentItem.status == ContentStatus.PENDING))
            ).all()
        ]
        assert pending_ids == [10], "limit=1 时应回收最旧的 id=10"

    await engine.dispose()


@pytest.mark.asyncio
async def test_requeue_service_gated_by_budget_headroom(monkeypatch):
    """预算余量不足时不发起回收（不触碰 repo）。"""
    from unittest.mock import AsyncMock

    reset_mock = AsyncMock(return_value=5)
    monkeypatch.setattr(ContentRepo, "reset_local_fallback_for_reanalysis", reset_mock)

    async def _no_headroom(min_ratio: float = 0.3) -> bool:
        return False

    monkeypatch.setattr("app.services.analysis_requeue.budget_headroom_ok", _no_headroom)

    count = await requeue_local_fallback_content(object())  # db 不应被触碰
    assert count == 0
    reset_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_budget_headroom_semantics(monkeypatch):
    # 全关（三窗全 0）→ 余量无限
    _set_budget(monkeypatch, 0, 0, 0)

    async def _boom():
        raise AssertionError("budget disabled must not query counts")

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _boom)
    assert await budget_headroom_ok() is True

    # 余量充足
    _set_budget(monkeypatch, 100, 2000, 20000)

    async def _counts():
        return 10, 500, 10000

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)
    assert await budget_headroom_ok() is True

    # 最紧窗口（日窗 10000/20000 = 50% 已用，余量 50% ≥30%）；改为 18000（余量 10%）→ False
    async def _tight():
        return 5, 100, 18000

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _tight)
    assert await budget_headroom_ok() is False

    # fail-closed：计数查询失败 → False（requeue 不发起）
    async def _db_error():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _db_error)
    assert await budget_headroom_ok() is False


@pytest.mark.asyncio
async def test_exempt_scenes_bypass_budget(monkeypatch):
    """日报/周报/月报等豁免场景超限仍放行；非豁免场景照常拒绝。"""
    _set_budget(monkeypatch, minute=1, hour=0, day=0)

    async def _counts():
        return 1, 0, 0  # 分钟窗已耗尽

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)

    for scene in ("daily_report", "weekly_digest", "monthly_digest"):
        await ensure_llm_budget(scene)  # 豁免：不抛

    with pytest.raises(LlmBudgetExceededError):
        await ensure_llm_budget("content_analysis")


@pytest.mark.asyncio
async def test_reset_skips_content_with_repeated_fallbacks():
    """已有 ≥2 条 local_fallback 分析的内容不再回收（防确定性降级无限循环）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="信源",
                source_type=SourceType.RSS,
                url="https://example.com/y.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        # id=20：两条 fallback 分析（requeue 重降级过一次）—— 不再回收
        db.add(_content(20, now=now))
        # id=21：一条 fallback —— 正常回收（对照组）
        db.add(_content(21, now=now))
        db.add_all(
            [
                AiAnalysis(
                    id=301,
                    content_id=20,
                    curation_score=62,
                    summary_source="local_fallback",
                    created_at=now - timedelta(hours=4),
                ),
                AiAnalysis(
                    id=302,
                    content_id=20,
                    curation_score=62,
                    summary_source="local_fallback",
                    created_at=now - timedelta(hours=2),
                ),
                AiAnalysis(
                    id=303,
                    content_id=21,
                    curation_score=62,
                    summary_source="local_fallback",
                    created_at=now - timedelta(hours=2),
                ),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        count = await repo.reset_local_fallback_for_reanalysis(limit=10)
        assert count == 1
        item20 = await db.get(ContentItem, 20)
        item21 = await db.get(ContentItem, 21)
        assert item20 is not None and item20.status == ContentStatus.ANALYZED
        assert item21 is not None and item21.status == ContentStatus.PENDING

    await engine.dispose()
