"""Start daily generation with one frozen version identity for HTTP and worker."""

from __future__ import annotations

import logging
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.core.task_registry import track_background_task
from app.repositories.daily_report_repo import DailyReportRepository
from app.services.daily_report import (
    LOCAL_TZ,
    WEEKDAYS,
    _day_window,
    _is_active_generating,
    _local_now,
    _local_today,
    _normalize_edition,
    generate_daily_report,
)

logger = logging.getLogger(__name__)


async def start_daily_report_generation(
    db: AsyncSession,
    *,
    target_date: date | None = None,
    edition: str | None = None,
    cutoff_at: datetime | None = None,
    force: bool = True,
    owner_user_id: int | None = None,
):
    target = target_date or _local_today()
    normalized_edition = _normalize_edition(edition, target, cutoff_at)
    # Use explicit local-zone timestamps for PostgreSQL timestamptz storage.
    # Recomputing now() in the worker can otherwise create a second version.
    start, end = _day_window(target, cutoff_at, normalized_edition)
    start, end = start.replace(tzinfo=LOCAL_TZ), end.replace(tzinfo=LOCAL_TZ)
    # Public rows have a NULL owner, so the ordinary UNIQUE constraint does not
    # serialize concurrent claims. Lock by logical job across DB sessions/workers.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:job_key, 0))"),
        {"job_key": f"daily-report:{owner_user_id}:{target.isoformat()}:{normalized_edition}"},
    )
    repo = DailyReportRepository(db)
    latest = await repo.find_existing_for_version(target.isoformat(), normalized_edition, owner_user_id)
    if latest and _is_active_generating(latest, _local_now()):
        return latest
    report = await repo.find_existing_for_version(target.isoformat(), normalized_edition, owner_user_id, cutoff_at=end)
    if report and report.status == "DONE" and not force:
        return report
    if report:
        repo.mark_generating(report)
    else:
        report = repo.create_generating_placeholder(
            report_date_iso=target.isoformat(),
            weekday=WEEKDAYS[target.weekday()],
            edition=normalized_edition,
            window_start=start,
            window_end=end,
            cutoff_at=end,
            owner_user_id=owner_user_id,
        )
    await repo.commit()
    report_id = report.id

    async def run():
        async with async_session() as bg_db:
            try:
                result = await generate_daily_report(
                    bg_db,
                    target_date=target,
                    edition=normalized_edition,
                    cutoff_at=end,
                    force=True,
                    owner_user_id=owner_user_id,
                )
                if result.id != report_id:
                    raise RuntimeError(f"情报生成记录不一致: expected={report_id}, actual={result.id}")
            except Exception as exc:
                logger.exception("Background daily report generation failed: id=%s", report_id)
                try:
                    await bg_db.rollback()
                    await DailyReportRepository(bg_db).mark_error(report_id, f"生成失败: {str(exc)[:200]}")
                except Exception:
                    logger.exception("Failed to mark daily report id=%s as ERROR", report_id)

    track_background_task(run(), name=f"daily-report-bg-{report_id}")
    return report
