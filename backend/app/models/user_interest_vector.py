"""UserInterestVector — per-user tag preference weights for personalization.

Stores aggregated tag weights derived from user behavior signals
(favorites, feedback, ignores). Used by the personalization boost
in today-picks scoring.

Design:
1. One row per (user_id, tag) — tag is a lowercase keyword from AiAnalysis.tags
   or ContentItem.category.
2. ``weight`` is a signed float: positive = user likes this tag,
   negative = user dislikes it. Magnitude reflects signal strength.
3. ``signal_source`` records which interaction type contributed most recently,
   for debugging and future decay strategies.
4. Updated asynchronously when favorites/feedback/ignores change.
5. Retention: tags with |weight| < 0.1 are pruned by the rebuild job.
"""

from __future__ import annotations

from datetime import datetime, UTC

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserInterestVector(Base):
    """Per-user tag preference weight for personalized ranking."""

    __tablename__ = "user_interest_vectors"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    tag: Mapped[str] = mapped_column(String(100), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    signal_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual"
    )  # favorite | feedback_positive | feedback_negative | ignore | manual
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "tag", name="uq_user_interest_tag"),
        Index("ix_user_interest_vectors_user", "user_id"),
        Index("ix_user_interest_vectors_user_weight", "user_id", "weight"),
    )
