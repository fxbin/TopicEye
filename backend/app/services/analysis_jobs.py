from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import select, update

from app.core.config import settings
from app.core.database import async_session
from app.models.analysis_job import AnalysisJobRecord
from app.repositories.content_repo import ContentRepo

MAX_TRACKED_ANALYSIS_JOBS = 100
logger = logging.getLogger(__name__)


class AnalysisJobPersistenceError(RuntimeError):
    """A claimed batch must never be left without a durable job record."""


@dataclass
class AnalysisJob:
    job_id: str
    content_ids: list[int]
    skipped_inflight_ids: list[int] = field(default_factory=list)
    status: str = "QUEUED"
    queued_at: datetime = field(default_factory=lambda: datetime.now(UTC))
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


def _job_from_record(record: AnalysisJobRecord) -> AnalysisJob:
    return AnalysisJob(
        job_id=record.job_id,
        content_ids=list(record.content_ids or []),
        skipped_inflight_ids=list(record.skipped_inflight_ids or []),
        status=record.status,
        queued_at=record.queued_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        analyzed_ids=list(record.analyzed_ids or []),
        failed_ids=list(record.failed_ids or []),
        error_message=record.error_message,
    )


async def _persist_job_snapshot(job: AnalysisJob, *, required: bool = False) -> bool:
    try:
        async with async_session() as db:

            async def _write_snapshot() -> None:
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

            await _write_snapshot()
        return True
    except Exception as exc:
        logger.warning("Analysis job %s snapshot persistence failed: %s", job.job_id, exc)
        if required:
            raise AnalysisJobPersistenceError(f"Unable to persist analysis job {job.job_id}") from exc
        return False


async def _get_persisted_job(job_id: str) -> dict[str, Any] | None:
    try:
        async with async_session() as db:
            record = await db.get(AnalysisJobRecord, job_id)
            return _record_dict(record) if record else None
    except Exception as exc:
        logger.warning("Analysis job %s persisted lookup skipped: %s", job_id, exc)
        return None


async def _load_persisted_job(job_id: str) -> AnalysisJob | None:
    try:
        async with async_session() as db:
            record = await db.get(AnalysisJobRecord, job_id)
            return _job_from_record(record) if record else None
    except Exception as exc:
        logger.warning("Analysis job %s persisted load failed: %s", job_id, exc)
        return None


async def _cache_job(job: AnalysisJob) -> None:
    async with _lock:
        _jobs[job.job_id] = job
        if job.status in {"QUEUED", "RUNNING"}:
            _active_content_ids.update(job.content_ids)
        else:
            _active_content_ids.difference_update(job.content_ids)
        _prune_jobs()


async def create_analysis_job(content_ids: list[int]) -> AnalysisJob:
    """Persist a batch before it is handed to any best-effort executor.

    ``_jobs`` remains a small process-local read cache only.  The durable
    record is required because FastAPI background tasks disappear on restart.
    """
    unique_ids = list(dict.fromkeys(content_ids))
    async with _lock:
        _release_expired_active_ids(datetime.now(UTC))
        queued_ids = [content_id for content_id in unique_ids if content_id not in _active_content_ids]
        skipped_ids = [content_id for content_id in unique_ids if content_id in _active_content_ids]
        job = AnalysisJob(
            job_id=uuid4().hex,
            content_ids=queued_ids,
            skipped_inflight_ids=skipped_ids,
            status="QUEUED" if queued_ids else "SKIPPED",
            finished_at=None if queued_ids else datetime.now(UTC),
        )
        _jobs[job.job_id] = job
        _active_content_ids.update(queued_ids)
        _prune_jobs()
    try:
        await _persist_job_snapshot(job, required=True)
    except AnalysisJobPersistenceError:
        async with _lock:
            _jobs.pop(job.job_id, None)
            _active_content_ids.difference_update(job.content_ids)
        raise
    return job


async def mark_analysis_job_running(job_id: str) -> bool:
    """Atomically claim a queued persisted job for one executor.

    The compare-and-set is deliberately database-backed so an API background
    task and the scheduler recovery worker cannot both execute the same job.
    """
    started_at = datetime.now(UTC)
    try:
        async with async_session() as db:
            stmt = (
                update(AnalysisJobRecord)
                .where(AnalysisJobRecord.job_id == job_id, AnalysisJobRecord.status == "QUEUED")
                .values(status="RUNNING", started_at=started_at, finished_at=None, error_message=None)
            )
            result = await db.execute(stmt)
            await db.commit()
            if result.rowcount != 1:
                return False
            record = await db.get(AnalysisJobRecord, job_id)
    except Exception as exc:
        logger.warning("Analysis job %s could not be claimed: %s", job_id, exc)
        # Keep legacy callers usable in tests/maintenance commands where the
        # optional analysis_jobs table has not been migrated yet.  Production
        # request paths require durable creation before reaching this point.
        async with _lock:
            cached = _jobs.get(job_id)
            if cached is None or cached.status != "QUEUED":
                return False
            cached.status = "RUNNING"
            cached.started_at = started_at
        return True

    if record is not None:
        await _cache_job(_job_from_record(record))
    return True


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
    if job is None:
        job = await _load_persisted_job(job_id)
    if job is None:
        logger.warning("Analysis job %s completion ignored because no durable record exists", job_id)
        return

    async with _lock:
        # A newer cache entry may have arrived while the persisted record was
        # loaded.  Preserve that entry's current state where possible.
        job = _jobs.get(job_id, job)
        analyzed = list(dict.fromkeys(analyzed_ids or []))
        failed = list(dict.fromkeys(failed_ids or []))
        job.analyzed_ids = analyzed
        job.failed_ids = failed
        job.error_message = error_message[:1000] if error_message else None
        job.finished_at = datetime.now(UTC)
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
        await _persist_job_snapshot(job_to_persist, required=True)


async def get_analysis_job(job_id: str) -> dict[str, Any] | None:
    async with _lock:
        job = _jobs.get(job_id)
        if job:
            return _job_dict(job)
    return await _get_persisted_job(job_id)


async def recover_interrupted_analysis_jobs() -> list[str]:
    """Requeue jobs left RUNNING by a previous process before dispatching.

    This is called once by scheduler startup.  A periodic dispatcher only
    consumes ``QUEUED`` jobs, so a healthy in-process worker is never reset.
    Content-level lease fencing remains the final ownership guard.
    """
    recovered_ids: list[str] = []
    try:
        async with async_session() as db:
            result = await db.execute(select(AnalysisJobRecord).where(AnalysisJobRecord.status == "RUNNING"))
            records = list(result.scalars().all())
            for record in records:
                record.status = "QUEUED"
                record.started_at = None
                record.error_message = "Recovered after worker process restart"
                recovered_ids.append(record.job_id)
            await db.commit()
    except Exception as exc:
        logger.warning("Analysis job recovery skipped: %s", exc)
        return []

    for job_id in recovered_ids:
        job = await _load_persisted_job(job_id)
        if job is not None:
            await _cache_job(job)
    if recovered_ids:
        logger.info("Requeued %d interrupted analysis jobs", len(recovered_ids))
    return recovered_ids


async def run_analysis_job(job_id: str) -> dict[str, Any] | None:
    """Execute one durable job after atomically acquiring its queued state."""
    if not await mark_analysis_job_running(job_id):
        return await get_analysis_job(job_id)

    job = await _load_persisted_job(job_id)
    if job is None:
        return None
    content_ids = [
        content_id
        for content_id in job.content_ids
        if content_id not in set(job.analyzed_ids) and content_id not in set(job.failed_ids)
    ]
    if not content_ids:
        await finish_analysis_job(job_id, analyzed_ids=job.analyzed_ids, failed_ids=job.failed_ids)
        return await get_analysis_job(job_id)

    claim_tokens = await _load_claim_tokens(content_ids)
    runnable_ids = list(claim_tokens)
    unavailable_ids = [content_id for content_id in content_ids if content_id not in claim_tokens]
    if not runnable_ids:
        await finish_analysis_job(job_id, failed_ids=content_ids, error_message="Analysis claim is no longer owned")
        return await get_analysis_job(job_id)

    try:
        from app.services.analysis import analyze_batch_concurrent

        results = await analyze_batch_concurrent(
            runnable_ids,
            assume_claimed=True,
            claim_tokens=claim_tokens,
        )
        analyzed_ids = [item.content_id for item in results]
        failed_ids = [
            content_id for content_id in runnable_ids if content_id not in set(analyzed_ids)
        ] + unavailable_ids
        if failed_ids:
            await _release_analysis_claims(
                {content_id: claim_tokens[content_id] for content_id in failed_ids if content_id in claim_tokens}
            )
        await finish_analysis_job(job_id, analyzed_ids=analyzed_ids, failed_ids=failed_ids)
    except Exception as exc:
        await _release_analysis_claims(claim_tokens)
        await finish_analysis_job(job_id, failed_ids=content_ids, error_message=str(exc))
        logger.exception("Analysis job %s failed", job_id)
    return await get_analysis_job(job_id)


async def dispatch_queued_analysis_jobs(*, limit: int = 20) -> list[str]:
    """Run persisted queued jobs; safe to call from the periodic scheduler."""
    try:
        async with async_session() as db:
            result = await db.execute(
                select(AnalysisJobRecord.job_id)
                .where(AnalysisJobRecord.status == "QUEUED")
                .order_by(AnalysisJobRecord.queued_at)
                .limit(max(1, limit))
            )
            job_ids = list(result.scalars().all())
    except Exception as exc:
        logger.warning("Analysis job dispatcher lookup failed: %s", exc)
        return []

    dispatched: list[str] = []
    for job_id in job_ids:
        status = await run_analysis_job(job_id)
        if status and status["status"] != "QUEUED":
            dispatched.append(job_id)
    return dispatched


async def _load_claim_tokens(content_ids: list[int]) -> dict[int, str]:
    """Capture current ownership once; never release a claim by ID alone."""
    claim_tokens: dict[int, str] = {}
    try:
        async with async_session() as db:
            content_repo = ContentRepo(db)
            for content_id in content_ids:
                content = await content_repo.get_by_id(content_id)
                if content is not None and content.analysis_claim_token:
                    claim_tokens[content_id] = content.analysis_claim_token
    except Exception:
        logger.exception("Failed to load analysis claim tokens for content_ids=%s", content_ids)
    return claim_tokens


async def _release_analysis_claims(claim_tokens: dict[int, str]) -> int:
    if not claim_tokens:
        return 0
    try:
        async with async_session() as db:
            content_repo = ContentRepo(db)
            released = 0
            for content_id, fencing_token in claim_tokens.items():
                released += int(await content_repo.release_analysis_claim(content_id, fencing_token))
            await db.commit()
            return released
    except Exception:
        # Do not let a best-effort release prevent the durable job terminal
        # state from being recorded.  Lease recovery will reclaim leftovers.
        logger.exception("Failed to release analysis claims for job content_ids=%s", list(claim_tokens))
        return 0


async def reset_analysis_jobs() -> None:
    """Clear in-memory job state for tests and process-local maintenance."""
    async with _lock:
        _jobs.clear()
        _active_content_ids.clear()
