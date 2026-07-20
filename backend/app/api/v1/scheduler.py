"""
Scheduled Jobs & Execution Logs API endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.api.v1.auth import get_current_admin_user
from app.services.job_tracker import get_all_job_configs, get_recent_logs

router = APIRouter(prefix="/scheduler", tags=["scheduler"], dependencies=[Depends(get_current_admin_user)])
logger = logging.getLogger(__name__)


@router.get("/jobs")
async def list_jobs():
    """List all scheduled job configurations with last run info."""
    jobs = await get_all_job_configs()
    return {"jobs": jobs, "total": len(jobs)}


@router.get("/logs")
async def list_logs(
    job_key: str = Query(None, description="Filter by job_key"),
    limit: int = Query(50, ge=1, le=200, description="Max records"),
):
    """List recent job execution logs."""
    logs = await get_recent_logs(job_key=job_key or "", limit=limit)
    return {"logs": logs, "total": len(logs)}
