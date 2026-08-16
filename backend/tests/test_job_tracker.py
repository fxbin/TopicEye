import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.scheduled_job import ScheduledJob
from app.services import job_tracker


@pytest.mark.asyncio
async def test_track_job_skips_overlapping_run(monkeypatch):
    calls = {"body": 0, "logs": [], "finished": [], "last": []}
    started = asyncio.Event()
    release = asyncio.Event()

    async def fake_create_log(job_key: str, trigger_type: str = "scheduler"):
        log_id = len(calls["logs"]) + 1
        calls["logs"].append({"id": log_id, "job_key": job_key, "trigger_type": trigger_type})
        return log_id

    async def fake_finish_log(
        log_id: int, status: str, result_summary: str = "", error_message: str = "", duration_ms: int = 0
    ):
        calls["finished"].append(
            {
                "id": log_id,
                "status": status,
                "result_summary": result_summary,
                "error_message": error_message,
                "duration_ms": duration_ms,
            }
        )

    async def fake_update_last(job_key: str, status: str):
        calls["last"].append((job_key, status))

    async def fake_claim_job(job_key: str, name: str, description: str, timeout: int):
        calls.setdefault("claims", []).append((job_key, name, description, timeout))
        return True

    monkeypatch.setattr(job_tracker, "_claim_job_run", fake_claim_job)
    monkeypatch.setattr(job_tracker, "_create_log", fake_create_log)
    monkeypatch.setattr(job_tracker, "_finish_log", fake_finish_log)
    monkeypatch.setattr(job_tracker, "_update_job_last_run", fake_update_last)
    job_tracker._job_locks.pop("overlap_test", None)

    @job_tracker.track_job("overlap_test", name="重叠测试", timeout=5)
    async def tracked_job():
        calls["body"] += 1
        started.set()
        await release.wait()
        return "done"

    first = asyncio.create_task(tracked_job())
    await started.wait()
    second = await tracked_job()
    release.set()
    await first

    assert second is None
    assert calls["body"] == 1
    assert calls["claims"] == [("overlap_test", "重叠测试", "", 5)]
    assert [item["status"] for item in calls["finished"]] == ["SKIPPED", "SUCCESS"]
    assert calls["finished"][0]["result_summary"] == "同一任务仍在运行，本次触发已跳过"
    assert calls["last"] == [("overlap_test", "SUCCESS")]


@pytest.mark.asyncio
async def test_track_job_skips_when_database_lease_is_active(monkeypatch):
    calls = {"body": 0, "logs": [], "finished": [], "last": [], "claims": []}

    async def fake_claim_job(job_key: str, name: str, description: str, timeout: int):
        calls["claims"].append((job_key, name, description, timeout))
        return False

    async def fake_create_log(job_key: str, trigger_type: str = "scheduler"):
        log_id = len(calls["logs"]) + 1
        calls["logs"].append({"id": log_id, "job_key": job_key, "trigger_type": trigger_type})
        return log_id

    async def fake_finish_log(
        log_id: int, status: str, result_summary: str = "", error_message: str = "", duration_ms: int = 0
    ):
        calls["finished"].append(
            {
                "id": log_id,
                "status": status,
                "result_summary": result_summary,
                "error_message": error_message,
                "duration_ms": duration_ms,
            }
        )

    async def fake_update_last(job_key: str, status: str):
        calls["last"].append((job_key, status))

    monkeypatch.setattr(job_tracker, "_claim_job_run", fake_claim_job)
    monkeypatch.setattr(job_tracker, "_create_log", fake_create_log)
    monkeypatch.setattr(job_tracker, "_finish_log", fake_finish_log)
    monkeypatch.setattr(job_tracker, "_update_job_last_run", fake_update_last)
    job_tracker._job_locks.pop("lease_test", None)

    @job_tracker.track_job("lease_test", name="租约测试", timeout=7, description="跨进程")
    async def tracked_job():
        calls["body"] += 1
        return "done"

    result = await tracked_job()

    assert result is None
    assert calls["body"] == 0
    assert calls["claims"] == [("lease_test", "租约测试", "跨进程", 7)]
    assert [item["status"] for item in calls["finished"]] == ["SKIPPED"]
    assert calls["finished"][0]["result_summary"] == "同一任务仍在运行，本次触发已跳过"
    assert calls["last"] == []


@pytest.mark.asyncio
async def test_claim_job_run_uses_database_lease(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(job_tracker, "async_session", session_factory)

    first_claim = await job_tracker._claim_job_run("db_lease", "数据库租约", "", 30)
    second_claim = await job_tracker._claim_job_run("db_lease", "数据库租约", "", 30)

    assert first_claim is True
    assert second_claim is False

    async with session_factory() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.job_key == "db_lease"))
        job = result.scalar_one()
        assert job.last_status == "RUNNING"
        job.last_run_at = datetime.now(UTC) - timedelta(seconds=120)
        await db.commit()

    stale_claim = await job_tracker._claim_job_run("db_lease", "数据库租约", "", 30)

    assert stale_claim is True

    await job_tracker._release_job_run("db_lease", "SUCCESS")
    async with session_factory() as db:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.job_key == "db_lease"))
        job = result.scalar_one()
        assert job.last_status == "SUCCESS"

    await engine.dispose()
