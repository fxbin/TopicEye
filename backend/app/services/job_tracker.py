"""
JobTracker — decorator + service for tracking scheduled job execution.

Usage:
    @track_job("daily_report", timeout=300)
    async def _generate_daily_report():
        ...

Every invocation is logged to job_execution_logs with start/end/status/duration.
"""

from __future__ import annotations

import asyncio
import functools
import logging
import time
import traceback
from datetime import datetime, timezone, UTC
from typing import Optional
from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.database import async_session
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.scheduled_job import JobExecutionLog, ScheduledJob

logger = logging.getLogger(__name__)
_job_locks: dict[str, asyncio.Lock] = {}


def _get_job_lock(job_key: str) -> asyncio.Lock:
    lock = _job_locks.get(job_key)
    if lock is None:
        lock = asyncio.Lock()
        _job_locks[job_key] = lock
    return lock


async def _upsert_job_config(job_key: str, name: str, description: str = "") -> None:
    """Ensure scheduled_jobs has a record for this job_key (idempotent)."""
    async with async_session() as db:
        existing = await db.execute(select(ScheduledJob).where(ScheduledJob.job_key == job_key))
        job = existing.scalar_one_or_none()
        if job:
            # Update name/description if changed
            if job.name != name or (description and job.description != description):
                job.name = name
                if description:
                    job.description = description
                await db.commit()
            return
        job = ScheduledJob(
            job_key=job_key,
            name=name,
            job_type="cron",
            description=description or name,
            enabled=True,
            timeout_seconds=300,
        )
        db.add(job)
        await db.commit()


async def _claim_job_run(job_key: str, name: str, description: str, timeout: int) -> bool:
    """Acquire a cross-process lease for a scheduled job run."""
    for attempt in range(3):
        now = datetime.now(UTC)
        async with async_session() as db:

            async def _claim() -> bool:
                await begin_immediate_for_sqlite(db)
                existing = await db.execute(
                    select(ScheduledJob).where(ScheduledJob.job_key == job_key).with_for_update()
                )
                job = existing.scalar_one_or_none()
                if job is None:
                    job = ScheduledJob(
                        job_key=job_key,
                        name=name,
                        job_type="cron",
                        description=description or name,
                        enabled=True,
                        timeout_seconds=timeout,
                        last_run_at=now,
                        last_status="RUNNING",
                    )
                    db.add(job)
                    await db.flush()
                    return True

                lease_seconds = max(int(timeout), 1)
                stale_cutoff = now.timestamp() - lease_seconds
                last_run_ts = job.last_run_at.timestamp() if job.last_run_at else 0
                if job.last_status == "RUNNING" and last_run_ts > stale_cutoff:
                    return False

                job.name = name
                job.description = description or job.description or name
                job.timeout_seconds = timeout
                job.last_run_at = now
                job.last_status = "RUNNING"
                job.updated_at = now
                await db.flush()
                return True

            try:
                claimed = await retry_sqlite_locked(_claim, on_retry=db.rollback)
                await db.commit()
                return claimed
            except IntegrityError:
                await db.rollback()
                if attempt == 2:
                    raise
                await asyncio.sleep(0.05 * (attempt + 1))

    return False


async def _release_job_run(job_key: str, status: str) -> None:
    """Release the cross-process job lease with the final status."""
    await _update_job_last_run(job_key, status)


async def _create_log(job_key: str, trigger_type: str = "scheduler") -> int:
    """Insert a RUNNING log entry, return its id."""
    async with async_session() as db:
        log = JobExecutionLog(
            job_key=job_key,
            status="RUNNING",
            started_at=datetime.now(UTC),
            trigger_type=trigger_type,
        )
        db.add(log)
        await db.commit()
        return log.id


async def _finish_log(
    log_id: int, status: str, result_summary: str = "", error_message: str = "", duration_ms: int = 0
) -> None:
    """Update log entry with final status."""
    from sqlalchemy import select

    async with async_session() as db:
        existing = await db.execute(select(JobExecutionLog).where(JobExecutionLog.id == log_id))
        log = existing.scalar_one_or_none()
        if not log:
            return
        log.status = status
        log.finished_at = datetime.now(UTC)
        log.duration_ms = duration_ms
        if result_summary:
            log.result_summary = result_summary[:2000]
        if error_message:
            log.error_message = error_message[:4000]
        await db.commit()


async def _update_job_last_run(job_key: str, status: str) -> None:
    """Update scheduled_jobs.last_run_at and last_status."""
    async with async_session() as db:
        existing = await db.execute(select(ScheduledJob).where(ScheduledJob.job_key == job_key))
        job = existing.scalar_one_or_none()
        if job:
            job.last_run_at = datetime.now(UTC)
            job.last_status = status
            await db.commit()


async def _record_skipped_job(job_key: str, trigger_type: str, summary: str) -> None:
    """Record a skipped trigger consistently."""
    log_id = await _create_log(job_key, trigger_type=trigger_type)
    await _finish_log(
        log_id,
        "SKIPPED",
        result_summary=summary,
        duration_ms=0,
    )


def track_job(job_key: str, name: str = "", timeout: int = 300, description: str = "", trigger_type: str = "scheduler"):
    """Decorator that wraps an async job function with execution tracking.

    Args:
        job_key: Unique identifier for this job (e.g. "daily_report")
        name: Human-readable name (auto-derived from function name if empty)
        timeout: Max seconds before marking as TIMEOUT
        description: Job description stored in scheduled_jobs
        trigger_type: "scheduler" or "manual"
    """

    def decorator(func: Callable) -> Callable:
        _name = name or func.__name__

        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            lock = _get_job_lock(job_key)
            skip_summary = "同一任务仍在运行，本次触发已跳过"
            if lock.locked():
                await _record_skipped_job(job_key, trigger_type, skip_summary)
                logger.info("Job %s skipped because another run is active", job_key)
                return

            claimed = await _claim_job_run(job_key, _name, description, timeout)
            if not claimed:
                await _record_skipped_job(job_key, trigger_type, skip_summary)
                logger.info("Job %s skipped because another process holds the lease", job_key)
                return

            async with lock:
                log_id = await _create_log(job_key, trigger_type=trigger_type)
                start = time.monotonic()
                status = "SUCCESS"
                result_summary = ""
                error_message = ""

                try:
                    result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
                    if isinstance(result, str):
                        result_summary = result[:2000]
                    elif isinstance(result, dict):
                        import json

                        result_summary = json.dumps(result, ensure_ascii=False)[:2000]
                    elif result is not None:
                        result_summary = str(result)[:2000]
                except TimeoutError:
                    status = "TIMEOUT"
                    error_message = f"Job timed out after {timeout}s"
                    logger.error("Job %s timed out after %ds", job_key, timeout)
                except Exception as e:
                    status = "FAILED"
                    error_message = f"{type(e).__name__}: {str(e)}"
                    logger.exception("Job %s failed", job_key)
                finally:
                    duration_ms = int((time.monotonic() - start) * 1000)

                await _finish_log(
                    log_id,
                    status,
                    result_summary=result_summary,
                    error_message=error_message,
                    duration_ms=duration_ms,
                )
                await _release_job_run(job_key, status)

                logger.info(
                    "Job %s %s in %dms",
                    job_key,
                    status,
                    duration_ms,
                )

        # Attach metadata for scheduler registration
        wrapper._job_key = job_key
        wrapper._job_name = _name
        wrapper._job_description = description
        return wrapper

    return decorator


# ── Query helpers ──────────────────────────────────────────────────────


async def get_recent_logs(job_key: str = "", limit: int = 50) -> list[dict]:
    """Get recent execution logs, optionally filtered by job_key."""
    from sqlalchemy import select, desc

    async with async_session() as db:
        q = select(JobExecutionLog).order_by(desc(JobExecutionLog.started_at)).limit(limit)
        if job_key:
            q = q.where(JobExecutionLog.job_key == job_key)
        result = await db.execute(q)
        logs = result.scalars().all()
        return [
            {
                "id": l.id,
                "job_key": l.job_key,
                "status": l.status,
                "started_at": l.started_at.isoformat() if l.started_at else None,
                "finished_at": l.finished_at.isoformat() if l.finished_at else None,
                "duration_ms": l.duration_ms,
                "result_summary": l.result_summary,
                "error_message": l.error_message,
                "trigger_type": l.trigger_type,
            }
            for l in logs
        ]


async def get_all_job_configs() -> list[dict]:
    """Get all scheduled job configurations with last run info."""
    from sqlalchemy import select

    async with async_session() as db:
        result = await db.execute(select(ScheduledJob).order_by(ScheduledJob.id))
        jobs = result.scalars().all()
        return [
            {
                "id": j.id,
                "job_key": j.job_key,
                "name": j.name,
                "job_type": j.job_type,
                "cron_expr": j.cron_expr,
                "interval_seconds": j.interval_seconds,
                "enabled": j.enabled,
                "timeout_seconds": j.timeout_seconds,
                "description": j.description,
                "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None,
                "last_status": j.last_status,
            }
            for j in jobs
        ]
