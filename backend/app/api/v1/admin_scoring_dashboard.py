"""
Admin Scoring Dashboard API — feedback analytics + recommendation quality.

- GET /admin/scoring-dashboard   Aggregated feedback + personalization stats
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.repositories.scoring_dashboard_repo import ScoringDashboardRepository

router = APIRouter(
    prefix="/admin/scoring-dashboard",
    tags=["admin-scoring-dashboard"],
    dependencies=[Depends(get_current_admin_user)],
)


@router.get("")
async def get_scoring_dashboard(
    days: int = Query(7, ge=1, le=90, description="统计时间范围（天）"),
    db: AsyncSession = Depends(get_db),
):
    """Return aggregated feedback + recommendation quality stats."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    repo = ScoringDashboardRepository(db)
    data = await repo.get_dashboard_data(cutoff=cutoff)
    return {"period_days": days, **data}
