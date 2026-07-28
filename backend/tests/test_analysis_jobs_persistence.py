from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1 import analyses as analyses_api
from app.core.database import Base
from app.models.analysis import AiAnalysis  # noqa: F401
from app.models.analysis_job import AnalysisJobRecord
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source  # noqa: F401
from app.services import analysis, analysis_jobs


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_interrupted_analysis_job_is_requeued_and_dispatched_after_restart(monkeypatch):
    """The DB record, rather than the old process cache, drives recovery."""
    await analysis_jobs.reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(analysis_jobs, "async_session", session_factory)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="需要恢复的后台任务",
                url="https://example.com/recover-analysis-job",
                status=ContentStatus.ANALYZING,
                analysis_claim_token="claimed-before-restart",
                analysis_lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                crawled_at=datetime.now(UTC),
            )
        )
        await db.commit()

    job = await analysis_jobs.create_analysis_job([1])
    assert await analysis_jobs.mark_analysis_job_running(job.job_id) is True

    # Simulate process loss: only the persisted RUNNING record survives.
    await analysis_jobs.reset_analysis_jobs()
    assert await analysis_jobs.recover_interrupted_analysis_jobs() == [job.job_id]

    async def fake_analyze(content_ids, **_kwargs):
        assert content_ids == [1]
        async with session_factory() as db:
            content = await db.get(ContentItem, 1)
            content.status = ContentStatus.ANALYZED
            db.add(AiAnalysis(content_id=1, summary="恢复完成", curation_score=60))
            await db.commit()
        return [SimpleNamespace(content_id=1)]

    monkeypatch.setattr(analysis, "analyze_batch_concurrent", fake_analyze)
    assert await analysis_jobs.dispatch_queued_analysis_jobs() == [job.job_id]

    async with session_factory() as db:
        record = await db.get(AnalysisJobRecord, job.job_id)
        content = await db.get(ContentItem, 1)
    assert record is not None
    assert record.status == "SUCCESS"
    assert record.analyzed_ids == [1]
    assert content.status == ContentStatus.ANALYZED

    await engine.dispose()
    await analysis_jobs.reset_analysis_jobs()


@pytest.mark.asyncio
async def test_only_one_executor_can_claim_a_persisted_analysis_job(monkeypatch):
    await analysis_jobs.reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(analysis_jobs, "async_session", session_factory)

    job = await analysis_jobs.create_analysis_job([11])
    assert await analysis_jobs.mark_analysis_job_running(job.job_id) is True
    assert await analysis_jobs.mark_analysis_job_running(job.job_id) is False

    async with session_factory() as db:
        record = await db.get(AnalysisJobRecord, job.job_id)
    assert record is not None
    assert record.status == "RUNNING"

    await engine.dispose()
    await analysis_jobs.reset_analysis_jobs()


@pytest.mark.asyncio
async def test_legacy_background_adapter_delegates_to_fenced_job_runner(monkeypatch):
    """The old callable must not perform ID-only claim release itself."""
    invoked: list[str] = []

    async def fake_run(job_id: str):
        invoked.append(job_id)

    monkeypatch.setattr(analyses_api, "run_analysis_job", fake_run)
    await analyses_api._run_batch_background("legacy-job", [1, 2])

    assert invoked == ["legacy-job"]
