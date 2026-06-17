"""
Daily Report API endpoints.
"""

from __future__ import annotations

from typing import Tuple, Optional

from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.daily_report import DailyReport
from app.models.user import User
from app.repositories.daily_report_repo import DailyReportRepository
from app.schemas.daily_report import (
    DailyReportResponse,
    DailyReportListResponse,
    DailyReportDatesResponse,
    DailyReportCalendarResponse,
)
from app.services.daily_report import LOCAL_TZ, WEEKDAYS, generate_daily_report, get_latest_today_report
from app.services.plan_catalog import plan_allows_private_source

router = APIRouter(prefix="/daily-reports", tags=["daily-reports"], dependencies=[Depends(get_current_user)])


# ── /me series: user-owned private daily reports (T2) ───────────────────
# Declared BEFORE /today so FastAPI matches the literal "me" segment first.


@router.get("/me/today", response_model=DailyReportResponse)
async def get_my_today_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get today's user-owned daily report, generating one if none exists.

    Requires ``plan_allows_private_source`` (Pro and above). T1-3a shares
    the same paywall.
    """
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    return await get_latest_today_report(db, owner_user_id=current_user.id)


@router.get("/me/by-date", response_model=DailyReportResponse)
async def get_my_report_by_date(
    date: str = Query(..., description="Report date in YYYY-MM-DD format"),
    edition: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the user's own report for a date, or latest snapshot if final does not exist."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    repo = DailyReportRepository(db)
    report = await repo.get_by_date(date, edition=edition, owner_user_id=current_user.id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No my-report found for {date}")
    return report


@router.get("/me/dates", response_model=DailyReportDatesResponse)
async def list_my_report_dates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all dates that have the user's own reports, newest first."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    repo = DailyReportRepository(db)
    dates = await repo.get_dates_with_reports(owner_user_id=current_user.id)
    return {"dates": dates}


@router.post("/me/generate", response_model=DailyReportResponse)
async def trigger_my_generate(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force generate today's user-owned daily report snapshot."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    return await generate_daily_report(db, force=True, owner_user_id=current_user.id)


@router.get("/today", response_model=DailyReportResponse)
async def get_today_report(db: AsyncSession = Depends(get_db)):
    """Get today's latest daily report snapshot, generating one if none exists."""
    report = await get_latest_today_report(db)
    return report


@router.get("/by-date", response_model=DailyReportResponse)
async def get_report_by_date(
    date: str = Query(..., description="Report date in YYYY-MM-DD format"),
    edition: str | None = Query(None, description="Optional edition: snapshot/noon/evening/final/manual"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch final report for a date, or latest snapshot if final does not exist."""
    repo = DailyReportRepository(db)
    report = await repo.get_by_date(date, edition=edition)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No report found for {date}")
    return report


@router.get("/dates", response_model=DailyReportDatesResponse)
async def list_report_dates(db: AsyncSession = Depends(get_db)):
    """List all dates that have reports, newest first."""
    repo = DailyReportRepository(db)
    dates = await repo.get_dates_with_reports()
    return {"dates": dates}


@router.get("/calendar", response_model=DailyReportCalendarResponse)
async def get_report_calendar(
    days: int = Query(30, ge=7, le=90, description="Number of recent days to include"),
    db: AsyncSession = Depends(get_db),
):
    """Return a recent date map for spotting missing or failed daily reports."""
    today = datetime.now(LOCAL_TZ).date()
    start = today - timedelta(days=days - 1)
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.report_date >= start.isoformat())
        .where(DailyReport.report_date <= today.isoformat())
        .order_by(DailyReport.report_date.desc(), DailyReport.cutoff_at.desc(), DailyReport.updated_at.desc())
    )
    reports = result.scalars().all()

    grouped: dict[str, list[DailyReport]] = {}
    for report in reports:
        grouped.setdefault(report.report_date, []).append(report)

    calendar_statuses = {"DONE", "ERROR", "GENERATING", "MISSING"}

    def pick_calendar_report(items: list[DailyReport], current_date: date_cls) -> tuple[DailyReport | None, str]:
        if not items:
            return None, "MISSING"

        if current_date < today:
            final_reports = [item for item in items if item.edition == "final"]
            if not final_reports:
                return items[0], "MISSING"
            selected = final_reports[0]
            return selected, selected.status if selected.status in calendar_statuses else "MISSING"

        done = [item for item in items if item.status == "DONE"]
        if done:
            return done[0], "DONE"
        selected = items[0]
        return selected, selected.status if selected.status in calendar_statuses else "MISSING"

    out = []
    counts = {"DONE": 0, "ERROR": 0, "GENERATING": 0, "MISSING": 0}
    for offset in range(days):
        current = today - timedelta(days=offset)
        key = current.isoformat()
        selected, status = pick_calendar_report(grouped.get(key, []), current)
        if status not in counts:
            status = "MISSING"
        counts[status] += 1
        out.append(
            {
                "report_date": key,
                "weekday": WEEKDAYS[current.weekday()],
                "status": status,
                "edition": selected.edition if selected else None,
                "generated_at": selected.generated_at if selected else None,
                "cutoff_at": selected.cutoff_at if selected else None,
                "takeaway": selected.takeaway[:80] if selected and selected.takeaway else None,
                "content_count": selected.content_count if selected else 0,
                "analyzed_count": selected.analyzed_count if selected else 0,
                "topic_count": selected.topic_count if selected else 0,
                "has_report": selected is not None and status != "MISSING",
                "can_generate": status in {"MISSING", "ERROR", "DONE"},
                "is_today": current == today,
            }
        )

    return {
        "days": out,
        "total_days": days,
        "done_count": counts["DONE"],
        "error_count": counts["ERROR"],
        "missing_count": counts["MISSING"],
        "generating_count": counts["GENERATING"],
    }


@router.get("", response_model=DailyReportListResponse)
async def list_reports(
    limit: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """List recent daily reports."""
    count_result = await db.execute(select(func.count()).select_from(DailyReport))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(DailyReport).order_by(DailyReport.report_date.desc(), DailyReport.cutoff_at.desc()).limit(limit)
    )
    items = result.scalars().all()

    return {"items": items, "total": total}


@router.post("/generate", response_model=DailyReportResponse)
async def trigger_generate(db: AsyncSession = Depends(get_db)):
    """Force generate a daily report snapshot for a date/window."""
    report = await generate_daily_report(db, force=True)
    return report


@router.post("/generate-version", response_model=DailyReportResponse)
async def trigger_generate_version(
    target_date: str | None = Query(None, description="Target date in YYYY-MM-DD, defaults to today"),
    edition: str | None = Query(None, description="snapshot/noon/evening/final/manual"),
    cutoff_at: str | None = Query(None, description="ISO datetime cutoff, defaults to now"),
    force: bool = Query(True, description="Regenerate even if this exact version exists"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a specific daily report version/window."""
    parsed_date = date_cls.fromisoformat(target_date) if target_date else None
    parsed_cutoff = datetime.fromisoformat(cutoff_at) if cutoff_at else None
    report = await generate_daily_report(
        db,
        target_date=parsed_date,
        edition=edition,
        cutoff_at=parsed_cutoff,
        force=force,
    )
    return report
