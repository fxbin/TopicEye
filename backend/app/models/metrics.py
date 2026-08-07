from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.content import ContentItem


class ContentMetrics(Base):
    __tablename__ = "content_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    views: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    likes: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    comments: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    shares: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    favorites: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    followers_count: Mapped[int | None] = mapped_column(Integer, nullable=True, default=0)
    engagement_rate: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    explosion_ratio: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    content: Mapped[ContentItem] = relationship(back_populates="metrics")

    __table_args__ = (
        # selectinload(ContentItem.metrics) — WHERE content_id IN (...)
        Index("ix_content_metrics_content_id", "content_id"),
    )
