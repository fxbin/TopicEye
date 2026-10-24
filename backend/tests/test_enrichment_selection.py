"""Enrichment selection/claim transaction checks on disposable PostgreSQL."""

import asyncio
import os
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.repositories.analysis_repo import AnalysisRepository
from app.services.enrichment_selection import claim_pending_enrichment_ids


@pytest_asyncio.fixture
async def pg_candidates():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        now = datetime.now(UTC)
        for content_id in [1, 2, 3]:
            db.add(
                ContentItem(
                    id=content_id,
                    title=f"candidate {content_id}",
                    url=f"https://example.test/{content_id}",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                )
            )
        await db.flush()
        for content_id in [1, 2, 3]:
            db.add(
                AiAnalysis(
                    id=content_id,
                    content_id=content_id,
                    curation_score=95 - content_id,
                    info_density=90,
                    actionability=90,
                    source_weight=90,
                    creator_score=90,
                    viral_score=90,
                    freshness_score=90,
                    quality_score=90,
                    hot_score=90,
                    risk_score=0,
                    enrichment_status="pending",
                    created_at=now,
                )
            )
        await db.commit()
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_repository_claim_skips_real_locks_and_preserves_supplied_rank(pg_candidates):
    async with pg_candidates() as owner, pg_candidates() as competitor:
        await owner.execute(select(AiAnalysis).where(AiAnalysis.id == 2).with_for_update())
        claimed = await asyncio.wait_for(
            AnalysisRepository(competitor).claim_enrichment_candidates([3, 2, 1]), timeout=3
        )
        assert claimed == [3, 1]
        await competitor.commit()
        await owner.rollback()
    async with pg_candidates() as db:
        rows = (await db.execute(select(AiAnalysis.id, AiAnalysis.enrichment_status).order_by(AiAnalysis.id))).all()
        assert rows == [(1, "processing"), (2, "pending"), (3, "processing")]


@pytest.mark.asyncio
async def test_service_claim_does_not_commit_and_can_retry_after_rollback(pg_candidates):
    async with pg_candidates() as owner, pg_candidates() as competitor:
        claimed = await claim_pending_enrichment_ids(owner, min_score=55, limit=10)
        assert claimed == [1]
        # Uncommitted processing row remains invisible to another connection,
        # but the lock still prevents duplicate ownership.
        status = await competitor.scalar(select(AiAnalysis.enrichment_status).where(AiAnalysis.id == 1))
        assert status == "pending"
        assert await asyncio.wait_for(claim_pending_enrichment_ids(competitor, min_score=55, limit=10), timeout=3) == []
        await competitor.rollback()
        await owner.rollback()
        assert await claim_pending_enrichment_ids(competitor, min_score=55, limit=10) == [1]
        await competitor.commit()
    async with pg_candidates() as db:
        assert await db.scalar(select(AiAnalysis.enrichment_status).where(AiAnalysis.id == 1)) == "processing"
