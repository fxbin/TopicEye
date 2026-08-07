"""
Trend snapshot model — daily aggregates for trend tracking.

Stores per-topic and per-keyword daily statistics so the frontend can
render trend charts without re-computing from raw content every time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class TopicTrend(Base):
    """Daily snapshot of a topic group's stats."""

    __tablename__ = "topic_trends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # Topic-level trend (nullable for keyword-only snapshots)
    topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    topic_name: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Keyword-level trend
    keyword: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # Metrics
    content_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    avg_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    max_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pick_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Top items summary (JSON: [{title, url, score}])
    top_items: Mapped[str | None] = mapped_column(JSON, nullable=True)

    # Calculation provenance.  Legacy snapshots intentionally leave the exact
    # time window empty; they must not be presented as reconstructed evidence.
    calculation_version: Mapped[str] = mapped_column(String(50), nullable=False, default="legacy-v1")
    window_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provenance_status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="unavailable"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    members: Mapped[list[TopicTrendMember]] = relationship(
        back_populates="trend",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class TopicTrendMember(Base):
    """Frozen content membership for one topic or keyword trend snapshot."""

    __tablename__ = "topic_trend_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    trend_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("topic_trends.id", ondelete="CASCADE"),
        nullable=False,
    )
    # The content row can disappear after the snapshot.  The remaining
    # snapshot fields retain a usable historical attribution in that case.
    content_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)
    selected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    title_snapshot: Mapped[str] = mapped_column(String(500), nullable=False)
    url_snapshot: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_id_snapshot: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_name_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    platform_snapshot: Mapped[str | None] = mapped_column(String(100), nullable=True)
    published_at_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crawled_at_snapshot: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    time_basis: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    trend: Mapped[TopicTrend] = relationship(back_populates="members")

    __table_args__ = (
        UniqueConstraint("trend_id", "content_id", name="uq_topic_trend_member_content"),
        Index("ix_topic_trend_members_trend_position", "trend_id", "position"),
        Index("ix_topic_trend_members_content_id", "content_id"),
    )
