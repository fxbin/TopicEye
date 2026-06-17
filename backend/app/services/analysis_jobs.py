from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.core.config import settings
from app.core.database import async_session
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.analysis_job import AnalysisJobRecord


MAX_TRACKED_ANALYSIS_JOBS = 100
logger = logging.getLogger(__name__)


@dataclass
class AnalysisJob:
    job_id: str
    content_ids: list[int]
    skipped_inflight_ids: list[int] = field(default_factory=list)
    status: str = "QUEUED"
    queued_at: datetime = field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    finished_at: datetime | None = None
    analyzed_ids: list[int] = field(default_factory=list)
    failed_ids: list[int] = field(default_factory=list)
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        analyzed = set(self.analyzed_ids)
        failed = set(self.failed_ids)
        return {
            "job_id": self.job_id,
            "status": self.status,
            "content_ids": self.content_ids,
            "queued_ids": self.content_ids,
            "skipped_inflight_ids": self.skipped_inflight_ids,
            "analyzed_ids": self.analyzed_ids,
            "failed_ids": self.failed_ids,
            "pending_ids": [
                content_id for content_id in self.content_ids if content_id not in analyzed and content_id not in failed
            ],
            "count": len(self.content_ids),
            "queued_count": len(self.content_ids),
            "skipped_inflight_count": len(self.skipped_inflight_ids),
            "analyzed_count": len(self.analyzed_ids),
            "failed_count": len(self.failed_ids),
            "queued_at": self.queued_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
            "error_message": self.error_message,
        }


_jobs: OrderedDict[str, AnalysisJob] = OrderedDict()
_active_content_ids: set[int] = set()
_lock = asyncio.Lock()


def _prune_jobs() -> None:
    while len(_jobs) > MAX_TRACKED_ANALYSIS_JOBS:
        _jobs.popitem(last=False)


def _release_expired_active_ids(now: datetime) -> None:
    try:
        ttl_seconds = max(60, int(settings.ANALYSIS_JOB_INFLIGHT_TTL_SECONDS))
    except (TypeError, ValueError):
        ttl_seconds = 900

    expired_ids: set[int] = set()
    for job in _jobs.values():
        if job.status not in {"QUEUED", "RUNNING"}:
            continue
        anchor = job.started_at or job.queued_at
        if (now - anchor).total_seconds() > ttl_seconds:
            job.status = "EXPIRED"
            job.finished_at = now
            job.error_message = "Analysis job expired before reporting completion"
            expired_ids.update(job.content_ids)
    _active_content_ids.difference_update(expired_ids)


def _job_dict(job: AnalysisJob) -> dict[str, Any]:
    return job.to_dict()


def _record_dict(record: AnalysisJobRecord) -> dict[str, Any]:
    analyzed = set(record.analyzed_ids or [])
    failed = set(record.failed_ids or [])
    content_ids = record.content_ids or []
    skipped_ids = record.skipped_inflight_ids or []
    return {
        "job_id": record.job_id,
        "status": record.status,
        "content_ids": content_ids,
        "queued_ids": content_ids,
        "skipped_inflight_ids": skipped_ids,
        "analyzed_ids": record.analyzed_ids or [],
        "failed_ids": record.failed_ids or [],
        "pending_ids": [
            content_id for content_id in content_ids if content_id not in analyzed and content_id not in failed
        ],
        "count": len(content_ids),
        "queued_count": len(content_ids),
        "skipped_inflight_count": len(skipped_ids),
        "analyzed_count": len(record.analyzed_ids or []),
        "failed_count": len(record.failed_ids or []),
        "queued_at": record.queued_at.isoformat(),
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "finished_at": record.finished_at.isoformat() if record.finished_at else None,
        "error_message": record.error_message,
    }


async def _persist_job_snapshot(job: AnalysisJob) -> None:
    try:
        async with async_session() as db:

            async def _write_snapshot() -> None:
                await begin_immediate_for_sqlite(db)
                record = await db.get(AnalysisJobRecord, job.job_id)
                if record is None:
                    record = AnalysisJobRecord(job_id=job.job_id, status=job.status, content_ids=[])
                    db.add(record)
                record.status = job.status
                record.content_ids = list(job.content_ids)
                record.skipped_inflight_ids = list(job.skipped_inflight_ids)
                record.analyzed_ids = list(job.analyzed_ids)
                record.failed_ids = list(job.failed_ids)
                record.queued_at = job.queued_at
                record.started_at = job.started_at
                record.finished_at = job.finished_at
                record.error_message = job.error_message
                await db.commit()

            await retry_sqlite_locked(_write_snapshot, attempts=3, base_delay=0.05, on_retry=db.rollback)
    except Exception as exc:
        logger.warning("Analysis job %s snapshot persistence skipped: %s", job.job_id, exc)


async def _get_persisted_job(job_id: str) -> dict[str, Any] | None:
    try:
        async with async_session() as db:
            record = await db.get(AnalysisJobRecord, job_id)
            return _record_dict(record) if record else None
    except Exception as exc:
        logger.warning("Analysis job %s persisted lookup skipped: %s", job_id, exc)
        return None


async def create_analysis_job(content_ids: list[int]) -> AnalysisJob:
    """Register an analysis background job and deduplicate in-flight content IDs."""
    unique_ids = list(dict.fromkeys(content_ids))
    async with _lock:
        _release_expired_active_ids(datetime.now(timezone.utc))
        queued_ids = [content_id for content_id in unique_ids if content_id not in _active_content_ids]
        skipped_ids = [content_id for content_id in unique_ids if content_id in _active_content_ids]
        job = AnalysisJob(
            job_id=uuid4().hex,
            content_ids=queued_ids,
            skipped_inflight_ids=skipped_ids,
            status="QUEUED" if queued_ids else "SKIPPED",
            finished_at=None if queued_ids else datetime.now(timezone.utc),
        )
        _jobs[job.job_id] = job
        _active_content_ids.update(queued_ids)
        _prune_jobs()
    await _persist_job_snapshot(job)
    return job


async def mark_analysis_job_running(job_id: str) -> None:
    job_to_persist: AnalysisJob | None = None
    async with _lock:
        job = _jobs.get(job_id)
        if job and job.status == "QUEUED":
            job.status = "RUNNING"
            job.started_at = datetime.now(timezone.utc)
            job_to_persist = job
    if job_to_persist is not None:
        await _persist_job_snapshot(job_to_persist)


async def finish_analysis_job(
    job_id: str,
    *,
    analyzed_ids: list[int] | None = None,
    failed_ids: list[int] | None = None,
    error_message: str | None = None,
) -> None:
    job_to_persist: AnalysisJob | None = None
    async with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        analyzed = list(dict.fromkeys(analyzed_ids or []))
        failed = list(dict.fromkeys(failed_ids or []))
        job.analyzed_ids = analyzed
        job.failed_ids = failed
        job.error_message = error_message[:1000] if error_message else None
        job.finished_at = datetime.now(timezone.utc)
        if error_message:
            job.status = "FAILED"
        elif failed and analyzed:
            job.status = "PARTIAL"
        elif failed:
            job.status = "FAILED"
        else:
            job.status = "SUCCESS"
        _active_content_ids.difference_update(job.content_ids)
        job_to_persist = job
    if job_to_persist is not None:
        await _persist_job_snapshot(job_to_persist)


async def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    async with _lock:
        job = _jobs.get(job_id)
        if job:
            return _job_dict(job)
    return await _get_persisted_job(job_id)


async def reset_analysis_jobs() -> None:
    """Clear in-memory job state for tests and process-local maintenance."""
    async with _lock:
        _jobs.clear()
        _active_content_ids.clear()
