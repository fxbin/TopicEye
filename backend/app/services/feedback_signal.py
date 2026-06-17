"""Helpers for converting user feedback into scoring signals."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.feedback import UserFeedback


async def get_feedback_scores(db: AsyncSession, content_ids: list[int]) -> dict[int, float]:
    """Return summed latest per-user feedback score deltas keyed by content id."""
    if not content_ids:
        return {}

    latest_feedback = aliased(UserFeedback)
    latest_id = (
        select(latest_feedback.id)
        .where(latest_feedback.content_id == UserFeedback.content_id)
        .where(latest_feedback.user_id == UserFeedback.user_id)
        .order_by(latest_feedback.created_at.desc(), latest_feedback.id.desc())
        .limit(1)
        .correlate(UserFeedback)
        .scalar_subquery()
    )
    result = await db.execute(
        select(
            UserFeedback.content_id,
            func.coalesce(func.sum(UserFeedback.score_delta), 0.0),
        )
        .where(UserFeedback.content_id.in_(content_ids))
        .where(UserFeedback.id == latest_id)
        .group_by(UserFeedback.content_id)
    )
    return {int(content_id): float(score or 0) for content_id, score in result.all()}
