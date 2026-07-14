from datetime import datetime, timedelta, timezone, UTC

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType
from app.repositories.content_repo import ContentRepo
from app.services.content_serialization import content_with_latest_analysis
from app.services.scoring_flow import build_scoring_flow_payload, invalidate_scoring_flow_cache


@pytest.mark.asyncio
async def test_scoring_flow_candidates_use_analysis_presence_not_status():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=5,
            )
        )
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="已有分析但状态未同步",
                    url="https://example.com/analyzed-pending",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.PENDING,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="尚未分析",
                    url="https://example.com/no-analysis",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.PENDING,
                    crawled_at=now,
                ),
            ]
        )
        db.add(
            AiAnalysis(
                content_id=1,
                curation_score=82,
                info_density=75,
                actionability=70,
                source_weight=80,
                quality_score=78,
                hot_score=65,
                freshness_score=90,
                creator_score=72,
                viral_score=61,
                risk_score=15,
            )
        )
        await db.commit()

        repo = ContentRepo(db)
        cutoff = now - timedelta(hours=24)
        total = await repo.count_for_scoring(time_cutoff=cutoff)
        rows = await repo.list_scoring_rows(time_cutoff=cutoff, limit=10)

        assert total == 1
        assert [row.id for row in rows] == [1]
        assert rows[0].title == "已有分析但状态未同步"
        assert rows[0].source_weight_db == 5

    await engine.dispose()


@pytest.mark.asyncio
async def test_scoring_flow_diagnostics_include_requested_custom_window():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    invalidate_scoring_flow_cache()
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=5,
            )
        )
        db.add(
            ContentItem(
                id=1,
                title="自定义窗口样本",
                url="https://example.com/custom-window",
                source_id=1,
                source_name="测试信源",
                source_type="RSS",
                category="AI",
                status=ContentStatus.PENDING,
                crawled_at=now,
            )
        )
        db.add(
            AiAnalysis(
                content_id=1,
                curation_score=82,
                info_density=75,
                actionability=70,
                source_weight=80,
                quality_score=78,
                hot_score=65,
                freshness_score=90,
                creator_score=72,
                viral_score=61,
                risk_score=15,
            )
        )
        await db.commit()

        payload = await build_scoring_flow_payload(db, hours=96, limit=20)

        window_options = payload["diagnostics"]["window_options"]
        collected_window_options = payload["diagnostics"]["collected_window_options"]
        assert {"hours": 96, "count": 1} in window_options
        assert {"hours": 96, "count": 1} in collected_window_options
        assert [item["hours"] for item in window_options] == [24, 48, 96, 168, 720]

    invalidate_scoring_flow_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_analyses_relationship_orders_latest_last():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="多轮分析样本",
                url="https://example.com/multi-analysis",
                status=ContentStatus.ANALYZED,
                crawled_at=now,
            )
        )
        db.add_all(
            [
                AiAnalysis(
                    id=2,
                    content_id=1,
                    summary="较新的分析",
                    curation_score=90,
                    created_at=now + timedelta(minutes=1),
                ),
                AiAnalysis(
                    id=1,
                    content_id=1,
                    summary="较旧的分析",
                    curation_score=20,
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        item = await ContentRepo(db).get_detail(1)

        assert item is not None
        assert [analysis.id for analysis in item.analyses] == [1, 2]
        assert item.analyses[-1].summary == "较新的分析"

    await engine.dispose()


def test_content_serialization_uses_explicit_latest_analysis_ordering():
    now = datetime.now(UTC)
    item = ContentItem(
        id=1,
        title="乱序分析内容",
        url="https://example.com/shuffled-analyses",
        status=ContentStatus.ANALYZED,
        crawled_at=now,
        is_favorited=False,
        created_at=now,
        updated_at=now,
    )
    item.analyses = [
        AiAnalysis(id=9, content_id=1, summary="旧分析高 ID", created_at=now),
        AiAnalysis(id=2, content_id=1, summary="新分析", created_at=now + timedelta(minutes=1)),
        AiAnalysis(id=1, content_id=1, summary="旧分析低 ID", created_at=now - timedelta(minutes=1)),
    ]

    payload = content_with_latest_analysis(item)

    assert payload["analysis"]["summary"] == "新分析"


@pytest.mark.asyncio
async def test_report_window_uses_latest_analysis_for_risk_gate():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=5,
            )
        )
        db.add(
            ContentItem(
                id=1,
                title="旧低风险新高风险",
                url="https://example.com/latest-risk",
                source_id=1,
                source_name="测试信源",
                source_type="RSS",
                category="AI",
                status=ContentStatus.ANALYZED,
                crawled_at=now,
            )
        )
        db.add_all(
            [
                AiAnalysis(
                    id=2,
                    content_id=1,
                    curation_score=90,
                    risk_score=10,
                    created_at=now,
                ),
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=20,
                    risk_score=95,
                    created_at=now + timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        report_items = await repo.list_for_report_window(
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
        )
        scoring_items, total = await repo.list_for_scoring(limit=10)
        scoring_rows = await repo.list_scoring_rows(limit=10)
        latest = await db.scalar(select(AiAnalysis).where(AiAnalysis.id == 1))

        assert latest is not None
        assert report_items == []
        assert total == 1
        assert [item.id for item in scoring_items] == [1]
        assert scoring_items[0].analyses[-1].risk_score == 95
        assert [row.risk_score for row in scoring_rows] == [95]

    await engine.dispose()


@pytest.mark.asyncio
async def test_report_window_uses_unified_risk_threshold():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="统一风险门内",
                    url="https://example.com/risk-80",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="统一风险门外",
                    url="https://example.com/risk-83",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=90,
                    risk_score=80,
                    created_at=now,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    curation_score=90,
                    risk_score=83,
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        report_items = await repo.list_for_report_window(
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
        )

        assert [item.id for item in report_items] == [1]

    await engine.dispose()


@pytest.mark.asyncio
async def test_today_picks_fallback_uses_unified_risk_threshold():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="今日推荐风险门内",
                    url="https://example.com/today-risk-80",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="今日推荐风险门外",
                    url="https://example.com/today-risk-83",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=90,
                    risk_score=80,
                    created_at=now,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    curation_score=90,
                    risk_score=83,
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        items = await repo.list_for_today_picks(hours=24)

        assert [item.id for item in items] == [1]

    await engine.dispose()


@pytest.mark.asyncio
async def test_report_window_excludes_ignored_and_duplicates():
    """日报候选窗口应剔除 ignored 与 duplicate_of 内容（对齐 today-picks 口径）。"""
    from app.models.ignored import IgnoredItem
    from app.repositories.ignored_repo import IgnoredRepo

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="正常样本",
                    url="https://example.com/normal",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="已忽略",
                    url="https://example.com/ignored",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=3,
                    title="重复样本",
                    url="https://example.com/dup",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    duplicate_of=1,
                    crawled_at=now,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(id=1, content_id=1, curation_score=90, risk_score=10, created_at=now),
                AiAnalysis(id=2, content_id=2, curation_score=90, risk_score=10, created_at=now),
                AiAnalysis(id=3, content_id=3, curation_score=90, risk_score=10, created_at=now),
            ]
        )
        db.add(IgnoredItem(content_id=2))
        await db.commit()

        repo = ContentRepo(db)
        ignored_ids = await IgnoredRepo(db).list_ignored_ids()
        items = await repo.list_for_report_window(
            window_start=now - timedelta(hours=1),
            window_end=now + timedelta(hours=1),
            exclude_ids=ignored_ids,
        )

        ids = {item.id for item in items}
        assert 1 in ids, "正常样本应保留"
        assert 2 not in ids, "已忽略样本应被剔除"
        assert 3 not in ids, "重复样本应被剔除"

    await engine.dispose()


@pytest.mark.asyncio
async def test_scoring_flow_counts_respect_visible_user_id():
    """scoring_flow 的 count 应与行同口径尊重 visible_user_id（owner 过滤一致性）。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                weight=3,
            )
        )
        # id=1: 公共内容；id=2: 用户 99 的私有内容
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="公共内容",
                    url="https://example.com/public",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                    owner_user_id=None,
                ),
                ContentItem(
                    id=2,
                    title="用户99私有",
                    url="https://example.com/private-99",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                    owner_user_id=99,
                ),
                ContentItem(
                    id=3,
                    title="用户77私有",
                    url="https://example.com/private-77",
                    source_id=1,
                    source_name="测试信源",
                    source_type="RSS",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                    owner_user_id=77,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(id=1, content_id=1, curation_score=90, risk_score=10, created_at=now),
                AiAnalysis(id=2, content_id=2, curation_score=90, risk_score=10, created_at=now),
                AiAnalysis(id=3, content_id=3, curation_score=90, risk_score=10, created_at=now),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        cutoff = now - timedelta(hours=1)

        # 用户 99 视角：count 应只计公共 + 自己的（2 条），不计用户 77 的
        count_99 = await repo.count_for_scoring(time_cutoff=cutoff, visible_user_id=99)
        collected_99 = await repo.count_collected_for_scoring_window(time_cutoff=cutoff, visible_user_id=99)
        rows_99 = await repo.list_scoring_rows(time_cutoff=cutoff, limit=10, visible_user_id=99)

        assert count_99 == 2, f"用户99应只见 2 条（公共+自己），实际 {count_99}"
        assert collected_99 == 2, f"collected 也应只计 2 条，实际 {collected_99}"
        assert {row.id for row in rows_99} == {1, 2}

        # 全局视角（visible_user_id=None）：计全部 3 条
        count_all = await repo.count_for_scoring(time_cutoff=cutoff)
        assert count_all == 3, f"全局应见 3 条，实际 {count_all}"

    await engine.dispose()
