from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.api.v1._db_write import write_with_503
from app.api.v1.auth import get_current_user
from app.core.database import database_profile
from app.core.database import get_db
from app.core.sqlite_retry import begin_immediate_for_sqlite
from app.models.feedback import (
    FeedbackType,
    FEEDBACK_SCORE_DELTAS,
)
from app.models.user import User
from app.repositories.content_repo import ContentRepo
from app.repositories.feedback_repo import FeedbackRepository
from app.schemas.feedback import (
    FeedbackCreate,
    FeedbackResponse,
    FeedbackStatsResponse,
)
from app.services.content_read_cache import invalidate_content_read_caches

router = APIRouter(prefix="/feedback", tags=["feedback"])


def _is_feedback_unique_conflict(exc: IntegrityError) -> bool:
    message = str(exc).lower()
    return "uq_user_feedback_content_user" in message or (
        "user_feedback" in message and ("unique constraint" in message or "duplicate key" in message)
    )


async def _write_feedback(
    data: FeedbackCreate,
    db: AsyncSession,
    current_user: User,
    fb_type: FeedbackType,
):
    """写入用户反馈，处理 upsert + stale 清理。返回 UserFeedback 实例。"""
    content_repo = ContentRepo(db)
    content_id = await content_repo.get_id_by_id(data.content_id)
    if content_id is None:
        raise HTTPException(status_code=404, detail="Content not found")

    feedback_repo = FeedbackRepository(db)
    existing_feedback = list(
        await feedback_repo.list_user_feedbacks_by_content(data.content_id, current_user.id)
    )
    score_delta = FEEDBACK_SCORE_DELTAS[fb_type]
    existing = existing_feedback[0] if existing_feedback else None
    if existing is not None:
        existing.feedback_type = fb_type
        existing.score_delta = score_delta
        existing.comment = data.comment
        stale_ids = [feedback.id for feedback in existing_feedback[1:]]
        if stale_ids:
            await feedback_repo.delete_by_ids(stale_ids)
        await db.flush()
        await db.refresh(existing)
        return existing

    return await feedback_repo.create(
        user_id=current_user.id,
        content_id=data.content_id,
        feedback_type=fb_type,
        score_delta=score_delta,
        comment=data.comment,
    )


@router.post("", response_model=FeedbackResponse, status_code=201)
async def submit_feedback(
    data: FeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Submit feedback for a content item.

    Keeps one active feedback record per content item, allowing users to revise it.
    """
    # Validate feedback_type
    try:
        fb_type = FeedbackType(data.feedback_type)
    except ValueError:
        valid = ", ".join(t.value for t in FeedbackType)
        raise HTTPException(
            status_code=422,
            detail=f"Invalid feedback_type. Must be one of: {valid}",
        )

    async def _write():
        if database_profile.is_sqlite and not db.in_transaction():
            await begin_immediate_for_sqlite(db)
        try:
            return await _write_feedback(data, db, current_user, fb_type)
        except IntegrityError as exc:
            if not _is_feedback_unique_conflict(exc):
                raise
            await db.rollback()
            return await _write_feedback(data, db, current_user, fb_type)

    feedback = await write_with_503(db, _write)
    invalidate_content_read_caches()
    from app.services.interest_vector_service import trigger_vector_rebuild
    trigger_vector_rebuild(current_user.id)
    return feedback


@router.get("/content/{content_id}", response_model=list[FeedbackResponse])
async def get_content_feedback(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's feedback for a specific content item."""
    feedback_repo = FeedbackRepository(db)
    return list(await feedback_repo.list_by_content_and_user(content_id, current_user.id))


@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Get aggregated feedback statistics."""
    feedback_repo = FeedbackRepository(db)
    total = await feedback_repo.count_all()
    by_type = await feedback_repo.count_group_by_type()
    avg_score = await feedback_repo.avg_score_delta()

    return FeedbackStatsResponse(
        total=total,
        by_type=by_type,
        avg_score_delta=round(avg_score, 2),
    )
