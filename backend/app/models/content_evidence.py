"""
ContentEvidence — cross-source evidence and credible lead marks.

Two tables:
  - content_evidence_marks: O(1) summary per content item
  - content_evidence_links: per-evidence clickable links for detail page

Phase 1 focuses on cross-source signal (multi-platform same-event detection).
Phase 2 adds credible leads (primary/official/independent classification).
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CrossSourceLevel(enum.StrEnum):
    NONE = "none"
    CROSS_SOURCE = "cross_source"
    STRONG_CROSS_SOURCE = "strong_cross_source"


class EvidenceType(enum.StrEnum):
    CROSS_SOURCE = "cross_source"
    PRIMARY_SOURCE = "primary_source"
    OFFICIAL_LINK = "official_link"
    INDEPENDENT_REPORT = "independent_report"


class ContentEvidenceMark(Base):
    """Summary mark for a content item — read by today-picks cards (O(1))."""

    __tablename__ = "content_evidence_marks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    cross_source_level: Mapped[str] = mapped_column(
        String(30), nullable=False, default=CrossSourceLevel.NONE
    )
    platform_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    platforms: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    has_primary_source: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)  # noqa: F841
    has_official_source: Mapped[bool] = mapped_column(Integer, nullable=False, default=0)  # noqa: F841
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    independent_publisher_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("content_id", "owner_user_id", name="uq_evidence_marks_scope"),
        Index("ix_evidence_marks_content", "content_id"),
        Index("ix_evidence_marks_owner", "owner_user_id"),
    )


class ContentEvidenceLink(Base):
    """Per-evidence link — read by content detail page (audit trail)."""

    __tablename__ = "content_evidence_links"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    mark_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content_evidence_marks.id", ondelete="CASCADE"),
        nullable=False,
    )
    evidence_content_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True
    )
    evidence_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    publisher_family: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    time_delta_minutes: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    match_basis: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_evidence_links_mark", "mark_id"),
    )
