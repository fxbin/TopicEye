"""
Admin Evidence API — cross-source evidence stats + manual discovery trigger.

- GET  /admin/evidence/stats          Aggregated evidence statistics
- GET  /admin/evidence/effect-stats   Interaction rate comparison
- POST /admin/evidence/discover       Manually trigger cross-source evidence discovery
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.evidence_repo import EvidenceRepository

router = APIRouter(
    prefix="/admin/evidence",
    tags=["admin-evidence"],
    dependencies=[Depends(get_current_admin_user)],
)
logger = logging.getLogger(__name__)


@router.get("/stats")
async def get_evidence_stats(db: AsyncSession = Depends(get_db)):
    """Return aggregated evidence statistics for admin dashboard."""
    repo = EvidenceRepository(db)
    return await repo.get_stats()


@router.get("/effect-stats")
async def get_evidence_effect_stats(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    db: AsyncSession = Depends(get_db),
):
    """Compare interaction rates between evidence-marked and unmarked content.

    Returns per-group content counts, interaction counts by type, and
    rate lift (how much evidence marks improve each interaction type).
    """
    repo = EvidenceRepository(db)
    return await repo.get_effect_stats(days=days)


@router.post("/discover")
async def trigger_evidence_discovery(
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """Manually trigger cross-source evidence discovery."""
    from app.services.evidence_service import discover_cross_source_evidence

    stats = await discover_cross_source_evidence(db, hours=hours)
    await db.commit()
    logger.info("Admin triggered evidence discovery: %s", stats)
    return {"triggered": True, "stats": stats}
