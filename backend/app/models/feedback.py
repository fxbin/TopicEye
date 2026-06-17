from __future__ import annotations
from typing import Optional
import enum
from datetime import datetime, timezone, UTC
from sqlalchemy import Integer, Float, Text, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enum_types import value_enum


class FeedbackType(enum.StrEnum):
    like = "like"
    dislike = "dislike"
    skip = "skip"
    not_relevant = "not_relevant"
    outdated = "outdated"
    great_pick = "great_pick"


# Mapping from feedback type to score delta
FEEDBACK_SCORE_DELTAS: dict[FeedbackType, float] = {
    FeedbackType.like: +10.0,
    FeedbackType.dislike: -15.0,
    FeedbackType.skip: -5.0,
    FeedbackType.not_relevant: -20.0,
    FeedbackType.outdated: -10.0,
    FeedbackType.great_pick: +20.0,
}


class UserFeedback(Base):
    __tablename__ = "user_feedback"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    feedback_type: Mapped[str] = mapped_column(value_enum(FeedbackType), nullable=False)
    score_delta: Mapped[float] = mapped_column(Float, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    user = relationship("User")

    __table_args__ = (
        UniqueConstraint("content_id", "user_id", name="uq_user_feedback_content_user"),
        Index("ix_user_feedback_content_user", "content_id", "user_id"),
        Index("ix_user_feedback_user_created", "user_id", "created_at"),
    )
