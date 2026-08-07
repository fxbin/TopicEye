from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import trends as trends_api
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)
from app.models.content_evidence import ContentEvidenceMark
from app.models.topic import TopicGroup
from app.models.trend import TopicTrend, TopicTrendMember
from app.services.trends import (
    get_keyword_cloud,
    get_keyword_trend_evidence,
    get_topic_trend_evidence,
    snapshot_daily_trends,
)


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_snapshot_freezes_only_public_canonical_members_and_keyword_tags_once():
    engine, session_factory = await _session_factory()
    target = date.today()
    created_at = datetime.combine(target, datetime.min.time(), tzinfo=UTC).replace(hour=12)

    async with session_factory() as db:
        db.add(TopicGroup(id=1, name="公开 AI"))
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="公开 canonical",
                    url="https://example.com/public",
                    source_id=11,
                    source_name="公开 RSS",
                    source_type="RSS",
                    platform="web",
                    topic_id=1,
                    status=ContentStatus.ANALYZED,
                    published_at=created_at,
                    crawled_at=created_at,
                    created_at=created_at,
                ),
                ContentItem(
                    id=2,
                    title="不得公开",
                    url="https://example.com/private",
                    owner_user_id=7,
                    topic_id=1,
                    status=ContentStatus.ANALYZED,
                    crawled_at=created_at,
                    created_at=created_at,
                ),
                ContentItem(
                    id=3,
                    title="已归并的附属内容",
                    url="https://example.com/member",
                    topic_id=1,
                    status=ContentStatus.ANALYZED,
                    crawled_at=created_at,
                    created_at=created_at,
                ),
            ]
        )
        db.add_all(
            [
                AiAnalysis(id=1, content_id=1, curation_score=80, tags=["AI", "AI"], created_at=created_at),
                AiAnalysis(id=2, content_id=2, curation_score=99, tags=["私有"], created_at=created_at),
                AiAnalysis(id=3, content_id=3, curation_score=90, tags=["附属"], created_at=created_at),
            ]
        )
        db.add(
            ContentEventGroup(
                id=1,
                canonical_content_id=1,
                first_occurrence_at=created_at,
                last_occurrence_at=created_at,
                status=EventStatus.ACTIVE,
            )
        )
        db.add(
            ContentEventMember(
                event_group_id=1,
                content_id=3,
                confidence=0.9,
                match_method="test",
                review_status=EventReviewStatus.CONFIRMED,
            )
        )
        await db.commit()

        result = await snapshot_daily_trends(db, target)
        assert result == {"topics": 1, "keywords": 1, "date": target.isoformat()}

        snapshots = (await db.execute(select(TopicTrend).order_by(TopicTrend.id))).scalars().all()
        assert all(snapshot.provenance_status == "complete" for snapshot in snapshots)
        assert {snapshot.keyword for snapshot in snapshots if snapshot.keyword} == {"AI"}
        members = (await db.execute(select(TopicTrendMember))).scalars().all()
        assert {member.content_id for member in members} == {1}
        assert all(member.time_basis == "published_at" for member in members)
        assert all(member.source_name_snapshot == "公开 RSS" for member in members)
        assert await get_keyword_cloud(db, days=1) == [
            {"keyword": "AI", "count": 1, "traceability": "complete"}
        ]

        # Re-running a date replaces both aggregate and member truth rather
        # than leaving orphan members behind in SQLite test databases.
        await snapshot_daily_trends(db, target)
        assert (await db.execute(select(TopicTrendMember))).scalars().all()
        assert len((await db.execute(select(TopicTrendMember))).scalars().all()) == 2

    await engine.dispose()


@pytest.mark.asyncio
async def test_trend_evidence_returns_paged_marks_and_honest_legacy_status():
    engine, session_factory = await _session_factory()
    target = date.today()
    created_at = datetime.combine(target, datetime.min.time(), tzinfo=UTC).replace(hour=9)

    async with session_factory() as db:
        db.add(TopicGroup(id=1, name="AI"))
        db.add(
            ContentItem(
                id=1,
                title="可溯源内容",
                url="https://example.com/evidence",
                source_id=11,
                source_name="Example",
                source_type="RSS",
                platform="web",
                topic_id=1,
                status=ContentStatus.ANALYZED,
                crawled_at=created_at,
                created_at=created_at,
            )
        )
        db.add(AiAnalysis(content_id=1, curation_score=90, tags=["agent"], created_at=created_at))
        await db.commit()

        await snapshot_daily_trends(db, target)
        for member in (await db.execute(select(TopicTrendMember))).scalars().all():
            member.selected = True
        db.add(
            ContentEvidenceMark(
                content_id=1,
                cross_source_level="cross_source",
                platform_count=2,
                platforms=["web", "rss"],
                evidence_count=1,
                independent_publisher_count=2,
                has_primary_source=0,
                has_official_source=1,
            )
        )
        await db.flush()

        topic_payload = await get_topic_trend_evidence(
            db,
            topic_id=1,
            snapshot_date=target,
            evidence_filter="evidenced",
            page=1,
            page_size=20,
        )
        assert topic_payload is not None
        assert topic_payload["summary"]["provenance_status"] == "complete"
        assert topic_payload["total"] == 1
        assert topic_payload["items"][0]["evidence_mark"]["platforms"] == ["web", "rss"]
        assert topic_payload["items"][0]["evidence_mark"]["independent_publisher_count"] == 2

        keyword_payload = await get_keyword_trend_evidence(
            db,
            keyword="agent",
            days=1,
            evidence_filter="selected",
        )
        assert keyword_payload is not None
        assert keyword_payload["summary"]["provenance_status"] == "complete"
        assert keyword_payload["total"] == 1

        endpoint_payload = await trends_api.keyword_trend_evidence(
            keyword="agent",
            days=1,
            evidence_filter="selected",
            page=1,
            page_size=20,
            db=db,
        )
        assert endpoint_payload.items[0].evidence_mark is not None
        assert endpoint_payload.items[0].evidence_mark.platforms == ["web", "rss"]

        db.add(
            TopicTrend(
                snapshot_date=target,
                topic_id=99,
                topic_name="旧话题",
                content_count=3,
                top_items=[{"title": "旧样本", "url": "https://example.com/legacy", "score": 1}],
                provenance_status="sample_only",
                calculation_version="legacy-v1",
            )
        )
        await db.flush()
        legacy_payload = await get_topic_trend_evidence(
            db,
            topic_id=99,
            snapshot_date=target,
        )
        assert legacy_payload is not None
        assert legacy_payload["summary"]["provenance_status"] == "sample_only"
        assert legacy_payload["items"] == []
        assert legacy_payload["message"]

    await engine.dispose()
