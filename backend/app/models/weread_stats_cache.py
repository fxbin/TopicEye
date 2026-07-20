"""WeRead statistics cache model.

Caches WeRead reading stats (readdata) and shelf comparison data so the
frontend doesn't hit WeRead's API on every page load.  A daily scheduler
refreshes the cache at 05:00; the API layer reads from cache first and
falls back to a live fetch when the cache is stale or missing.

Two cache_type values:
  - ``readdata``: reading stats (total_read_time, read_days, prefer_books …)
                  keyed by (user_id, cache_type, read_type) where read_type
                  is all / week / month / year.
  - ``shelf``:    full bookshelf + notebook comparison data
                  keyed by (user_id, cache_type, read_type='all') — shelf
                  has no read_type variant, so 'all' is a placeholder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WeReadStatsCache(Base):
    """Cached WeRead stats / shelf data, refreshed daily by scheduler."""

    __tablename__ = "weread_stats_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # readdata = reading stats (duration, days, rank, preferences …)
    # shelf     = full bookshelf + notebook comparison
    cache_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # For readdata: all / week / month / year
    # For shelf: always 'all' (shelf has no period variant)
    read_type: Mapped[str] = mapped_column(String(10), nullable=False, default="all")
    # Full API response payload (standardized dict from weread_materials)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    # Error message if the last fetch failed (null = success)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # When the data was fetched from WeRead API
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "cache_type", "read_type", name="uq_weread_cache_user_type_period"),
        Index("ix_weread_cache_user_type", "user_id", "cache_type"),
    )

    def __repr__(self) -> str:
        return f"<WeReadStatsCache user={self.user_id} type={self.cache_type} read_type={self.read_type}>"
