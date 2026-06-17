"""
Weekly Digest API endpoints.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.weekly_digest import WeeklyDigest
from app.repositories.weekly_digest_repo import WeeklyDigestRepository
from app.schemas.weekly_digest import (
    WeeklyDigestResponse,
    WeeklyDigestListResponse,
    WeeklyDigestWeeksResponse,
)
from app.services.weekly_digest import generate_weekly_digest

router = APIRouter(prefix="/weekly-digests", tags=["weekly-digests"], dependencies=[Depends(get_current_user)])


@router.get("/current", response_model=WeeklyDigestResponse)
async def get_current_week_digest(db: AsyncSession = Depends(get_db)):
    """Get or generate the current week's digest."""
    digest = await generate_weekly_digest(db)
    return digest


@router.get("/by-week", response_model=WeeklyDigestResponse)
async def get_digest_by_week(
    week_key: str = Query(..., description="Week key in YYYY-WNN format, e.g. 2025-W21"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single digest by its week key."""
    repo = WeeklyDigestRepository(db)
    digest = await repo.get_by_week_key(week_key)
    if digest is None:
        raise HTTPException(status_code=404, detail=f"No digest found for {week_key}")
    return digest


@router.get("/weeks", response_model=WeeklyDigestWeeksResponse)
async def list_digest_weeks(db: AsyncSession = Depends(get_db)):
    """List all weeks that have digests, newest first."""
    repo = WeeklyDigestRepository(db)
    weeks = await repo.get_weeks_with_digests()
    return {"weeks": weeks}


@router.get("", response_model=WeeklyDigestListResponse)
async def list_digests(
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
):
    """List recent weekly digests."""
    count_result = await db.execute(select(func.count()).select_from(WeeklyDigest))
    total = count_result.scalar() or 0

    result = await db.execute(select(WeeklyDigest).order_by(WeeklyDigest.week_start.desc()).limit(limit))
    items = result.scalars().all()

    return {"items": items, "total": total}


@router.post("/generate", response_model=WeeklyDigestResponse)
async def trigger_generate(
    week_key: Optional[str] = Query(None, description="Week key to generate (defaults to current week)"),
    db: AsyncSession = Depends(get_db),
):
    """Force regenerate a weekly digest for the given week (or current week)."""
    # Parse week_key to a reference date for generation
    reference_date = None
    if week_key:
        # Parse "2025-W21" format: find the Monday of that week
        try:
            parts = week_key.split("-W")
            year = int(parts[0])
            week_num = int(parts[1])
            # ISO week date: Monday of the given ISO week
            reference_date = date.fromisocalendar(year, week_num, 1)
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=400, detail=f"Invalid week_key format: {week_key}. Use YYYY-WNN format, e.g. 2025-W21"
            )

    # Delete existing digest to force regeneration
    if reference_date:
        from app.services.weekly_digest import _get_week_range

        wk, _, _, _ = _get_week_range(reference_date)
    else:
        from app.services.weekly_digest import _get_week_range

        wk, _, _, _ = _get_week_range()

    existing = await db.execute(select(WeeklyDigest).where(WeeklyDigest.week_key == wk))
    existing_digest = existing.scalar_one_or_none()
    if existing_digest:
        existing_digest.status = "PENDING"
        await db.flush()

    digest = await generate_weekly_digest(db, reference_date=reference_date)
    return digest
