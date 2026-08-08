"""
AI Analysis API endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.content_repo import ContentRepo
from app.schemas.analysis import AiAnalysisResponse
from app.services.analysis import analyze_batch_concurrent, analyze_content, analyze_one_claimed
from app.services.analysis_jobs import (
    AnalysisJobPersistenceError,
    create_analysis_job,
    get_analysis_job,
    run_analysis_job,
)

router = APIRouter(prefix="/analyses", tags=["analyses"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


@router.post("/content/{content_id}", response_model=AiAnalysisResponse)
async def analyze_single(
    content_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Analyze a single content item."""
    content_repo = ContentRepo(db)
    analysis_repo = AnalysisRepository(db)

    try:
        await content_repo.get_by_id_or_raise(content_id, "Content")
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e

    # Check if already analyzed
    existing = await analysis_repo.get_by_content_id(content_id)
    if existing:
        return existing

    try:
        analysis = await analyze_one_claimed(
            content_id,
            db,
            analyzer=analyze_content,
            raise_on_failure=True,
        )
        if analysis is None:
            existing = await analysis_repo.get_by_content_id(content_id)
            if existing:
                return existing
            raise HTTPException(status_code=409, detail="Content is already being analyzed")
        return analysis
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Analysis failed for content_id=%d", content_id)
        raise HTTPException(status_code=500, detail="Analysis failed") from e


@router.post("/batch", response_model=list[AiAnalysisResponse])
async def analyze_batch_endpoint(
    content_ids: list[int],
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """Analyze multiple content items by IDs."""
    if not content_ids:
        raise HTTPException(status_code=400, detail="No content IDs provided")
    if len(content_ids) > 50:
        raise HTTPException(status_code=400, detail="Maximum 50 items per batch")
    return await analyze_batch_concurrent(content_ids)


@router.post("/pending")
async def analyze_all_pending(
    limit: int = Query(20, ge=1, le=100),
    hours: int | None = Query(
        None, ge=1, le=720, description="Only analyze pending items collected within this many hours"
    ),
    sync: bool = Query(False, description="Run analysis synchronously for diagnostics"),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(get_current_admin_user),
):
    """Trigger analysis for pending content items, optionally scoped to a recent window."""
    content_repo = ContentRepo(db)
    ids = await content_repo.claim_pending_analysis_ids(limit=limit, hours=hours)
    await db.commit()

    if not ids:
        return {
            "message": "No pending content to analyze",
            "count": 0,
            "ids": [],
            "queued_ids": [],
            "skipped_inflight_ids": [],
            "analyzed_ids": [],
            "job_id": None,
            "hours": hours,
            "mode": "sync" if sync else "background",
        }

    if not sync:
        try:
            job = await create_analysis_job(ids)
        except AnalysisJobPersistenceError as exc:
            # The content claim was committed before job registration.  Do not
            # release it by ID here: a lease may have been reclaimed by a
            # different worker.  The lease expiry path safely makes it
            # eligible again without violating fencing.
            raise HTTPException(status_code=503, detail="Analysis queue is temporarily unavailable") from exc
        if not job.content_ids:
            return {
                "message": "Analysis already queued for matching content",
                "count": 0,
                "ids": ids,
                "queued_ids": [],
                "skipped_inflight_ids": job.skipped_inflight_ids,
                "analyzed_ids": [],
                "job_id": job.job_id,
                "hours": hours,
                "mode": "background",
            }
        if background_tasks is None:
            background_tasks = BackgroundTasks()
        background_tasks.add_task(run_analysis_job, job.job_id)
        return {
            "message": f"Analysis queued for {len(job.content_ids)} items in background",
            "count": len(job.content_ids),
            "ids": ids,
            "queued_ids": job.content_ids,
            "skipped_inflight_ids": job.skipped_inflight_ids,
            "analyzed_ids": [],
            "job_id": job.job_id,
            "hours": hours,
            "mode": "background",
        }

    results = await analyze_batch_concurrent(ids, assume_claimed=True)
    return {
        "message": f"Analysis complete for {len(results)} items",
        "count": len(results),
        "ids": ids,
        "hours": hours,
        "queued_ids": [],
        "skipped_inflight_ids": [],
        "job_id": None,
        "mode": "sync",
        "analyzed_ids": [a.content_id for a in results],
    }


@router.get("/jobs/{job_id}")
async def get_analysis_job_status(job_id: str):
    """Return durable status for a background analysis job."""
    job = await get_analysis_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Analysis job not found")
    return job


@router.get("/content/{content_id}", response_model=AiAnalysisResponse)
async def get_analysis(content_id: int, db: AsyncSession = Depends(get_db)):
    """Get the AI analysis for a content item."""
    analysis_repo = AnalysisRepository(db)
    analysis = await analysis_repo.get_by_content_id(content_id)
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    return analysis


@router.get("")
async def list_analyses(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    min_creator_score: float | None = None,
    min_viral_score: float | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all analyses with optional score filters."""
    analysis_repo = AnalysisRepository(db)
    items, total = await analysis_repo.list_with_score_filter(
        page=page,
        page_size=page_size,
        min_creator_score=min_creator_score,
        min_viral_score=min_viral_score,
    )
    return {
        "items": [
            {
                "id": a.id,
                "content_id": a.content_id,
                "quality_score": a.quality_score,
                "hot_score": a.hot_score,
                "freshness_score": a.freshness_score,
                "creator_score": a.creator_score,
                "viral_score": a.viral_score,
                "risk_score": a.risk_score,
                "summary": a.summary,
                "recommended_reason": a.recommended_reason,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


async def _run_batch_background(job_id: str, content_ids: list[int]) -> None:
    """Legacy callable retained for integrations that invoke it directly.

    New requests enqueue :func:`run_analysis_job`, whose database CAS makes
    restart recovery safe.  It must not release IDs itself: a reclaimed lease
    may now belong to a different worker and only the durable executor has
    the ownership context needed to finish it safely.
    """
    del content_ids
    await run_analysis_job(job_id)
