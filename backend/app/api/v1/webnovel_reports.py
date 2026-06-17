"""
Webnovel report API endpoints.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.webnovel_report import build_weekly_webnovel_report

router = APIRouter(prefix="/webnovel/reports", tags=["webnovel-reports"])


@router.get("/weekly")
async def weekly_report(
    days: int = Query(7, ge=3, le=31),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return weekly webnovel ranking history and movement analysis."""
    return await build_weekly_webnovel_report(db, days=days)
