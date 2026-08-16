"""
EvidenceInteraction — lightweight tracking for evidence-labeled content.

Records user interactions (click, favorite, adopt) on content items
that carry cross-source evidence marks. Used in Phase 3 to validate
whether evidence labels improve pick quality.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EvidenceInteraction(Base):
    """Anonymous interaction event for evidence-labeled content."""

    __tablename__ = "evidence_interactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    interaction_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # click | favorite | unfavorite | adopt | feedback_positive | feedback_negative
    cross_source_level: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_evidence_interactions_content", "content_id"),
        Index("ix_evidence_interactions_type", "interaction_type"),
    )
