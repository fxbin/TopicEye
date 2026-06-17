from datetime import datetime, timezone, UTC
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.services import enricher


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_enrich_batch_runs_with_bounded_concurrency(monkeypatch):
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=index,
                    title=f"批量增强内容 {index}",
                    url=f"https://example.com/enrich-batch-{index}",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                )
                for index in (1, 2, 3)
            ]
        )
        db.add_all(
            [
                AiAnalysis(
                    id=index,
                    content_id=index,
                    summary=f"摘要 {index}",
                    curation_score=80,
                    enrichment_status="processing",
                    created_at=now,
                )
                for index in (1, 2, 3)
            ]
        )
        await db.commit()

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_enrich_content(content_id: int, db: AsyncSession):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        return {
            "background_knowledge": f"背景 {content_id}",
            "why_matters": "重要",
            "related_angles": [],
            "creator_tips": [],
            "story_hooks": [],
        }

    monkeypatch.setattr(enricher.settings, "ENRICHMENT_WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(enricher, "enrich_content", fake_enrich_content)

    async with session_factory() as db:
        results = await enricher.enrich_batch([1, 2, 3], db)

    async with session_factory() as db:
        rows = (await db.execute(select(AiAnalysis).order_by(AiAnalysis.id))).scalars().all()

    assert max_active == 2
    assert [item["status"] for item in results] == ["completed", "completed", "completed"]
    assert [row.enrichment_status for row in rows] == ["completed", "completed", "completed"]
    assert rows[0].enrichment["background_knowledge"] == "背景 1"
    await engine.dispose()
