from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.selectable import Select

from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.topic import TopicGroup
from app.models.trend import TopicTrend
from app.repositories.analysis_repo import AnalysisRepository
from app.services import creation, topic_clustering
from app.services.trends import snapshot_daily_trends


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_analysis_repository_reads_and_filters_latest_rows_only():
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(ContentItem(id=1, title="测试内容", url="https://example.com/1"))
        db.add_all(
            [
                AiAnalysis(
                    id=2,
                    content_id=1,
                    summary="旧分析",
                    curation_score=95,
                    creator_score=95,
                    enrichment_status="pending",
                    created_at=now,
                ),
                AiAnalysis(
                    id=1,
                    content_id=1,
                    summary="新分析",
                    curation_score=10,
                    creator_score=10,
                    enrichment_status="completed",
                    created_at=now + timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        repo = AnalysisRepository(db)
        latest = await repo.get_by_content_id(1)
        pending_ids = await repo.get_pending_enrichment_ids(min_score=70, limit=10)
        high_score_items, total = await repo.list_with_score_filter(min_creator_score=70)

        assert latest is not None
        assert latest.summary == "新分析"
        assert pending_ids == []
        assert high_score_items == []
        assert total == 0

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_enrichment_uses_unified_scorer_not_raw_curation_score():
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="原始高分但质量弱",
                    url="https://example.com/weak-enrich",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="统一评分高质量",
                    url="https://example.com/strong-enrich",
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
                    curation_score=95,
                    info_density=10,
                    actionability=10,
                    creator_score=10,
                    viral_score=10,
                    freshness_score=50,
                    quality_score=10,
                    hot_score=10,
                    risk_score=0,
                    enrichment_status="pending",
                    created_at=now,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    curation_score=70,
                    info_density=90,
                    actionability=90,
                    source_weight=70,
                    creator_score=90,
                    viral_score=70,
                    freshness_score=80,
                    quality_score=90,
                    hot_score=70,
                    risk_score=0,
                    enrichment_status="pending",
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        pending_ids = await AnalysisRepository(db).get_pending_enrichment_ids(min_score=55, limit=10)

        assert pending_ids == [2]

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_enrichment_claim_marks_processing_and_skips_reclaim():
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="待增强认领",
                url="https://example.com/enrichment-claim",
                category="AI",
                status=ContentStatus.ANALYZED,
                crawled_at=now,
            )
        )
        db.add(
            AiAnalysis(
                id=1,
                content_id=1,
                curation_score=75,
                info_density=90,
                actionability=90,
                source_weight=70,
                creator_score=90,
                viral_score=80,
                freshness_score=90,
                quality_score=90,
                hot_score=80,
                risk_score=0,
                enrichment_status="pending",
                created_at=now,
            )
        )
        await db.commit()

        repo = AnalysisRepository(db)
        claimed_ids = await repo.claim_pending_enrichment_ids(min_score=55, limit=10)
        await db.commit()
        second_claim = await repo.claim_pending_enrichment_ids(min_score=55, limit=10)
        analysis = await db.get(AiAnalysis, 1)

        assert claimed_ids == [1]
        assert second_claim == []
        assert analysis.enrichment_status == "processing"

    await engine.dispose()


@pytest.mark.asyncio
async def test_single_enrichment_claim_marks_latest_processing_and_skips_reclaim():
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="单条增强认领",
                url="https://example.com/single-enrichment-claim",
                category="AI",
                status=ContentStatus.ANALYZED,
                crawled_at=now,
            )
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    summary="旧分析",
                    curation_score=95,
                    enrichment_status="pending",
                    created_at=now - timedelta(minutes=1),
                ),
                AiAnalysis(
                    id=2,
                    content_id=1,
                    summary="新分析",
                    curation_score=75,
                    enrichment_status="pending",
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        repo = AnalysisRepository(db)
        claimed = await repo.claim_enrichment_for_content(1)
        await db.commit()
        second_claim = await repo.claim_enrichment_for_content(1)
        old_analysis = await db.get(AiAnalysis, 1)
        latest_analysis = await db.get(AiAnalysis, 2)

    assert claimed is not None
    assert claimed.id == 2
    assert second_claim is None
    assert old_analysis.enrichment_status == "pending"
    assert latest_analysis.enrichment_status == "processing"
    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_enrichment_claim_retries_sqlite_write_lock(monkeypatch):
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    calls = {"begin": 0}

    async def flaky_begin_immediate(_db):
        calls["begin"] += 1
        if calls["begin"] == 1:
            raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    monkeypatch.setattr("app.repositories.analysis_repo.begin_immediate_for_sqlite", flaky_begin_immediate)

    # sqlite write lock 重试路径: 必须 is_sqlite=True 才会进 begin_immediate 分支
    class FakeProfile:
        is_sqlite = True
        is_postgresql = False

    monkeypatch.setattr("app.repositories.analysis_repo.database_profile", FakeProfile())

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="增强锁重试",
                url="https://example.com/enrichment-lock-retry",
                category="AI",
                status=ContentStatus.ANALYZED,
                crawled_at=now,
            )
        )
        db.add(
            AiAnalysis(
                id=1,
                content_id=1,
                curation_score=75,
                info_density=90,
                actionability=90,
                source_weight=70,
                creator_score=90,
                viral_score=80,
                freshness_score=90,
                quality_score=90,
                hot_score=80,
                risk_score=0,
                enrichment_status="pending",
                created_at=now,
            )
        )
        await db.commit()

        claimed_ids = await AnalysisRepository(db).claim_pending_enrichment_ids(min_score=55, limit=10)
        await db.commit()
        analysis = await db.get(AiAnalysis, 1)

        assert calls["begin"] == 2
        assert claimed_ids == [1]
        assert analysis.enrichment_status == "processing"

    await engine.dispose()


@pytest.mark.asyncio
async def test_pending_enrichment_claim_uses_skip_locked_for_postgresql(monkeypatch):
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    calls = {"skip_locked": 0}

    class FakeProfile:
        is_sqlite = False
        is_postgresql = True

    monkeypatch.setattr("app.repositories.analysis_repo.database_profile", FakeProfile())
    original_with_for_update = Select.with_for_update

    def with_for_update_spy(self, *args, **kwargs):
        if kwargs.get("skip_locked") is True:
            calls["skip_locked"] += 1
        return original_with_for_update(self, *args, **kwargs)

    monkeypatch.setattr(Select, "with_for_update", with_for_update_spy)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="增强并发认领一",
                    url="https://example.com/enrichment-pg-1",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="增强并发认领二",
                    url="https://example.com/enrichment-pg-2",
                    category="AI",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now - timedelta(minutes=1),
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=75,
                    info_density=90,
                    actionability=90,
                    source_weight=70,
                    creator_score=90,
                    viral_score=80,
                    freshness_score=90,
                    quality_score=90,
                    hot_score=80,
                    risk_score=0,
                    enrichment_status="pending",
                    created_at=now,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    curation_score=74,
                    info_density=90,
                    actionability=90,
                    source_weight=70,
                    creator_score=90,
                    viral_score=80,
                    freshness_score=90,
                    quality_score=90,
                    hot_score=80,
                    risk_score=0,
                    enrichment_status="pending",
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        claimed_ids = await AnalysisRepository(db).claim_pending_enrichment_ids(min_score=55, limit=10)
        await db.commit()

    assert calls["skip_locked"] == 1
    assert claimed_ids == [1]
    await engine.dispose()


@pytest.mark.asyncio
async def test_creation_plan_uses_latest_analysis_prompt_material(monkeypatch):
    captured_messages = []

    async def fake_call_llm_json(messages, scene, **_kwargs):
        captured_messages.extend(messages)
        return {
            "titles": ["新分析选题"],
            "structure": {"hook": "新 hook", "points": ["新观点"], "cta": "互动"},
        }

    monkeypatch.setattr(creation, "call_llm_json", fake_call_llm_json)
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="Runway 更新",
                url="https://example.com/runway",
                source_name="测试信源",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add_all(
            [
                AiAnalysis(
                    id=2,
                    content_id=1,
                    summary="旧分析摘要",
                    tags=["旧标签"],
                    created_at=now,
                ),
                AiAnalysis(
                    id=1,
                    content_id=1,
                    summary="新分析摘要",
                    tags=["新标签"],
                    created_at=now + timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        plan = await creation.generate_creation_plan(db, 1, "xiaohongshu")

        prompt_text = "\n".join(str(message["content"]) for message in captured_messages)
        assert plan["titles"] == ["新分析选题"]
        assert "新分析摘要" in prompt_text
        assert "新标签" in prompt_text
        assert "旧分析摘要" not in prompt_text

    await engine.dispose()


@pytest.mark.asyncio
async def test_clustering_uses_one_latest_analysis_per_content(monkeypatch):
    async def fake_name_clusters(clusters):
        return [
            {
                "name": "新标签话题",
                "summary": "只看新分析",
                "keywords": ["新标签"],
                "item_ids": [item["id"] for item in clusters[0]],
                "best_score": max(item["curation_score"] for item in clusters[0]),
                "content_count": len(clusters[0]),
            }
        ]

    monkeypatch.setattr(topic_clustering, "_name_clusters", fake_name_clusters)
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        for content_id in (1, 2):
            db.add(
                ContentItem(
                    id=content_id,
                    title=f"内容 {content_id}",
                    url=f"https://example.com/{content_id}",
                    status=ContentStatus.ANALYZED,
                )
            )
            db.add_all(
                [
                    AiAnalysis(
                        id=content_id + 10,
                        content_id=content_id,
                        tags=["旧标签"],
                        curation_score=90,
                        created_at=now,
                    ),
                    AiAnalysis(
                        id=content_id,
                        content_id=content_id,
                        tags=["新标签"],
                        curation_score=40 + content_id,
                        created_at=now + timedelta(minutes=1),
                    ),
                ]
            )
        await db.commit()

        stats = await topic_clustering.cluster_topics(db, use_llm_naming=True)
        topics = (await db.execute(select(TopicGroup))).scalars().all()

        assert stats["total"] == 2
        assert stats["clusters"] == 1
        assert len(topics) == 1
        assert topics[0].content_count == 2
        assert topics[0].best_score == 42

    await engine.dispose()


@pytest.mark.asyncio
async def test_clustering_topic_best_score_uses_unified_scorer(monkeypatch):
    async def fake_call_llm_json(_prompt, **_kwargs):
        return {"name": "统一评分", "summary": "看最终分"}

    monkeypatch.setattr(topic_clustering, "call_llm_json", fake_call_llm_json)
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="原始高分质量弱",
                    url="https://example.com/raw-high-topic",
                    status=ContentStatus.ANALYZED,
                    category="AI",
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="统一评分更强",
                    url="https://example.com/unified-topic",
                    status=ContentStatus.ANALYZED,
                    category="AI",
                    crawled_at=now,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    tags=["统一话题"],
                    curation_score=95,
                    info_density=10,
                    actionability=10,
                    creator_score=10,
                    viral_score=10,
                    freshness_score=50,
                    quality_score=10,
                    hot_score=10,
                    risk_score=0,
                    created_at=now,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    tags=["统一话题"],
                    curation_score=70,
                    info_density=90,
                    actionability=90,
                    source_weight=70,
                    creator_score=90,
                    viral_score=70,
                    freshness_score=80,
                    quality_score=90,
                    hot_score=70,
                    risk_score=0,
                    created_at=now,
                ),
            ]
        )
        await db.commit()

        stats = await topic_clustering.cluster_topics(db)
        topics = (await db.execute(select(TopicGroup))).scalars().all()

        assert stats["clusters"] == 1
        assert len(topics) == 1
        assert topics[0].best_score != 95
        assert topics[0].best_score > 70

    await engine.dispose()


@pytest.mark.asyncio
async def test_trend_snapshot_counts_latest_analysis_once():
    engine, session_factory = await _session_factory()
    target = date(2026, 6, 8)
    created_at = datetime(2026, 6, 8, 12, 0, 0)
    async with session_factory() as db:
        db.add(TopicGroup(id=1, name="AI话题"))
        db.add(
            ContentItem(
                id=1,
                title="趋势内容",
                url="https://example.com/trend",
                topic_id=1,
                status=ContentStatus.ANALYZED,
                created_at=created_at,
            )
        )
        db.add_all(
            [
                AiAnalysis(
                    id=2,
                    content_id=1,
                    curation_score=95,
                    tags=["旧关键词"],
                    created_at=created_at,
                ),
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=35,
                    tags=["新关键词"],
                    created_at=created_at + timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        result = await snapshot_daily_trends(db, target)
        trends = (await db.execute(select(TopicTrend))).scalars().all()
        topic_trend = next(item for item in trends if item.topic_id == 1)
        keywords = {item.keyword for item in trends if item.keyword}

        assert result == {"topics": 1, "keywords": 1, "date": "2026-06-08"}
        assert topic_trend.content_count == 1
        assert topic_trend.avg_score < 35.0
        assert topic_trend.max_score < 35.0
        assert topic_trend.pick_count == 0
        assert topic_trend.top_items[0]["score"] == topic_trend.max_score
        assert keywords == {"新关键词"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_trend_snapshot_uses_unified_scorer_for_picks_and_top_items():
    engine, session_factory = await _session_factory()
    target = date(2026, 6, 8)
    created_at = datetime(2026, 6, 8, 12, 0, 0)
    async with session_factory() as db:
        db.add(TopicGroup(id=1, name="AI话题"))
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="原始高分但质量弱",
                    url="https://example.com/weak",
                    category="AI",
                    topic_id=1,
                    status=ContentStatus.ANALYZED,
                    crawled_at=created_at,
                    created_at=created_at,
                ),
                ContentItem(
                    id=2,
                    title="统一评分高质量",
                    url="https://example.com/strong",
                    category="AI",
                    topic_id=1,
                    status=ContentStatus.ANALYZED,
                    crawled_at=created_at,
                    created_at=created_at,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=1,
                    content_id=1,
                    curation_score=95,
                    info_density=10,
                    actionability=10,
                    creator_score=10,
                    viral_score=10,
                    freshness_score=50,
                    quality_score=10,
                    hot_score=10,
                    risk_score=0,
                    tags=["弱质量"],
                    created_at=created_at,
                ),
                AiAnalysis(
                    id=2,
                    content_id=2,
                    curation_score=70,
                    info_density=90,
                    actionability=90,
                    source_weight=70,
                    creator_score=90,
                    viral_score=70,
                    freshness_score=80,
                    quality_score=90,
                    hot_score=70,
                    risk_score=0,
                    tags=["高质量"],
                    created_at=created_at,
                ),
            ]
        )
        await db.commit()

        result = await snapshot_daily_trends(db, target)
        trends = (await db.execute(select(TopicTrend))).scalars().all()
        topic_trend = next(item for item in trends if item.topic_id == 1)

        assert result["topics"] == 1
        assert topic_trend.content_count == 2
        assert topic_trend.pick_count == 1
        assert topic_trend.top_items[0]["title"] == "统一评分高质量"
        assert topic_trend.top_items[0]["score"] == topic_trend.max_score
        assert topic_trend.top_items[0]["score"] > topic_trend.top_items[1]["score"]

    await engine.dispose()
