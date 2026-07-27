"""
Trend snapshot model — daily aggregates for trend tracking.

Stores per-topic and per-keyword daily statistics so the frontend can
render trend charts without re-computing from raw content every time.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
