from __future__ import annotations
from typing import Optional
from datetime import datetime, timezone
from sqlalchemy import Integer, Float, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class ContentMetrics(Base):
    __tablename__ = "content_metrics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    views: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    likes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    comments: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    shares: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    favorites: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    followers_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=0)
    engagement_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0.0)
    explosion_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True, default=0.0)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    content: Mapped["ContentItem"] = relationship(back_populates="metrics")
