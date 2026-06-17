"""
Monthly Digest API endpoints.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.monthly_digest import MonthlyDigest
from app.repositories.monthly_digest_repo import MonthlyDigestRepository
from app.schemas.monthly_digest import (
    MonthlyDigestListResponse,
    MonthlyDigestMonthsResponse,
    MonthlyDigestResponse,
)
from app.services.monthly_digest import generate_monthly_digest

router = APIRouter(prefix="/monthly-digests", tags=["monthly-digests"], dependencies=[Depends(get_current_user)])


def _parse_month_key(month_key: str) -> date:
    try:
        year_text, month_text = month_key.split("-")
        year = int(year_text)
        month = int(month_text)
        return date(year, month, 1)
    except (ValueError, IndexError):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid month_key format: {month_key}. Use YYYY-MM, e.g. 2026-05",
        )


@router.get("/current", response_model=MonthlyDigestResponse)
async def get_current_month_digest(db: AsyncSession = Depends(get_db)):
    """Get or generate the latest full monthly digest."""
    return await generate_monthly_digest(db)


@router.get("/by-month", response_model=MonthlyDigestResponse)
async def get_digest_by_month(
    month_key: str = Query(..., description="Month key in YYYY-MM format, e.g. 2026-05"),
    db: AsyncSession = Depends(get_db),
):
    repo = MonthlyDigestRepository(db)
    digest = await repo.get_by_month_key(month_key)
    if digest is None:
        raise HTTPException(status_code=404, detail=f"No digest found for {month_key}")
    return digest


@router.get("/months", response_model=MonthlyDigestMonthsResponse)
async def list_digest_months(db: AsyncSession = Depends(get_db)):
    repo = MonthlyDigestRepository(db)
    months = await repo.get_months_with_digests()
    return {"months": months}


@router.get("", response_model=MonthlyDigestListResponse)
async def list_digests(limit: int = 12, db: AsyncSession = Depends(get_db)):
    count_result = await db.execute(select(func.count()).select_from(MonthlyDigest))
    total = count_result.scalar() or 0

    result = await db.execute(select(MonthlyDigest).order_by(MonthlyDigest.month_start.desc()).limit(limit))
    return {"items": result.scalars().all(), "total": total}


@router.post("/generate", response_model=MonthlyDigestResponse)
async def trigger_generate(
    month_key: str | None = Query(None, description="Month key to generate, YYYY-MM"),
    db: AsyncSession = Depends(get_db),
):
    reference_date = _parse_month_key(month_key) if month_key else None
    target_key = month_key
    if reference_date:
        target_key = f"{reference_date.year}-{reference_date.month:02d}"

    if target_key:
        existing = await db.execute(select(MonthlyDigest).where(MonthlyDigest.month_key == target_key))
        existing_digest = existing.scalar_one_or_none()
        if existing_digest:
            existing_digest.status = "PENDING"
            await db.flush()

    return await generate_monthly_digest(
        db,
        reference_date=reference_date,
        use_previous_month=reference_date is None,
    )
