"""
AI Analysis API endpoints.
"""

from __future__ import annotations
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import async_session
from app.core.dependencies import get_db
from app.core.exceptions import NotFoundError
from app.schemas.analysis import AiAnalysisResponse
from app.repositories.content_repo import ContentRepo
from app.repositories.analysis_repo import AnalysisRepository
from app.services.analysis import analyze_content, analyze_batch, analyze_batch_concurrent, analyze_one_claimed
from app.services.analysis_jobs import (
    create_analysis_job,
    finish_analysis_job,
    get_analysis_job,
    mark_analysis_job_running,
)

router = APIRouter(prefix="/analyses", tags=["analyses"], dependencies=[Depends(get_current_user)])


@router.post("/content/{content_id}", response_model=AiAnalysisResponse)
async def analyze_single(
    content_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Analyze a single content item."""
    content_repo = ContentRepo(db)
    analysis_repo = AnalysisRepository(db)

    try:
        content = await content_repo.get_by_id_or_raise(content_id, "Content")
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

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
        raise HTTPException(status_code=500, detail=f"Analysis failed: {str(e)}")


@router.post("/batch", response_model=list[AiAnalysisResponse])
async def analyze_batch_endpoint(
    content_ids: list[int],
    db: AsyncSession = Depends(get_db),
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
    hours: Optional[int] = Query(
        None, ge=1, le=720, description="Only analyze pending items collected within this many hours"
    ),
    sync: bool = Query(False, description="Run analysis synchronously for diagnostics"),
    background_tasks: BackgroundTasks = None,
    db: AsyncSession = Depends(get_db),
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
        job = await create_analysis_job(ids)
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
        background_tasks.add_task(_run_batch_background, job.job_id, job.content_ids)
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
    """Return process-local status for a background analysis job."""
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
    min_creator_score: Optional[float] = None,
    min_viral_score: Optional[float] = None,
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
    """Run batch analysis in background."""
    await mark_analysis_job_running(job_id)
    try:
        results = await analyze_batch_concurrent(content_ids, assume_claimed=True)
        analyzed_ids = [item.content_id for item in results]
        failed_ids = [content_id for content_id in content_ids if content_id not in set(analyzed_ids)]
        await _release_background_analysis_claims(failed_ids)
        await finish_analysis_job(job_id, analyzed_ids=analyzed_ids, failed_ids=failed_ids)
    except Exception as exc:
        await _release_background_analysis_claims(content_ids)
        await finish_analysis_job(job_id, failed_ids=content_ids, error_message=str(exc))
        raise


async def _release_background_analysis_claims(content_ids: list[int]) -> int:
    """Release still-analyzing background claims so failed jobs can be retried."""
    if not content_ids:
        return 0
    async with async_session() as db:
        released = await ContentRepo(db).release_analyzing_to_pending(content_ids)
        await db.commit()
        return released
