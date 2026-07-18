from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete, select, func
from sqlalchemy.exc import IntegrityError, OperationalError

from app.api.v1.auth import get_current_user
from app.core.database import database_profile
from app.core.database import get_db
from app.core.sqlite_retry import begin_immediate_for_sqlite, is_sqlite_locked, retry_sqlite_locked
from app.models.feedback import (
    UserFeedback,
    FeedbackType,
    FEEDBACK_SCORE_DELTAS,
)
from app.models.content import ContentItem
from app.models.user import User
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
) -> UserFeedback:
    content_id = await db.scalar(select(ContentItem.id).where(ContentItem.id == data.content_id))
    if content_id is None:
        raise HTTPException(status_code=404, detail="Content not found")

    existing_result = await db.execute(
        select(UserFeedback)
        .where(UserFeedback.content_id == data.content_id)
        .where(UserFeedback.user_id == current_user.id)
        .order_by(UserFeedback.created_at.desc(), UserFeedback.id.desc())
    )
    score_delta = FEEDBACK_SCORE_DELTAS[fb_type]
    existing_feedback = list(existing_result.scalars().all())
    existing = existing_feedback[0] if existing_feedback else None
    if existing is not None:
        existing.feedback_type = fb_type
        existing.score_delta = score_delta
        existing.comment = data.comment
        stale_ids = [feedback.id for feedback in existing_feedback[1:]]
        if stale_ids:
            await db.execute(delete(UserFeedback).where(UserFeedback.id.in_(stale_ids)))
        await db.flush()
        await db.refresh(existing)
        return existing

    feedback = UserFeedback(
        user_id=current_user.id,
        content_id=data.content_id,
        feedback_type=fb_type,
        score_delta=score_delta,
        comment=data.comment,
    )
    db.add(feedback)
    await db.flush()
    await db.refresh(feedback)
    return feedback


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

    try:
        feedback = await retry_sqlite_locked(_write, attempts=3, base_delay=0.1, on_retry=db.rollback)
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail="数据库繁忙，请稍后重试")
        raise
    invalidate_content_read_caches()
    return feedback


@router.get("/content/{content_id}", response_model=list[FeedbackResponse])
async def get_content_feedback(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get the current user's feedback for a specific content item."""
    result = await db.execute(
        select(UserFeedback)
        .where(UserFeedback.content_id == content_id)
        .where(UserFeedback.user_id == current_user.id)
        .order_by(UserFeedback.created_at.desc())
    )
    return list(result.scalars().all())


@router.get("/stats", response_model=FeedbackStatsResponse)
async def get_feedback_stats(
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Get aggregated feedback statistics."""
    # Total count
    total_result = await db.execute(select(func.count(UserFeedback.id)))
    total = total_result.scalar() or 0

    # Count by type
    type_result = await db.execute(
        select(
            UserFeedback.feedback_type,
            func.count(UserFeedback.id),
        ).group_by(UserFeedback.feedback_type)
    )
    by_type = {str(row[0]): row[1] for row in type_result.all()}

    # Average score delta
    avg_result = await db.execute(select(func.avg(UserFeedback.score_delta)))
    avg_score = avg_result.scalar() or 0.0

    return FeedbackStatsResponse(
        total=total,
        by_type=by_type,
        avg_score_delta=round(avg_score, 2),
    )
