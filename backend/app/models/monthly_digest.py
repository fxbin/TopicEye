"""
Monthly Digest model — AI-generated monthly curated newsletter.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MonthlyDigest(Base):
    __tablename__ = "monthly_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    month_key: Mapped[str] = mapped_column(String(7), unique=True, nullable=False, index=True)
    month_label: Mapped[str] = mapped_column(String(30), nullable=False)
    month_start: Mapped[str] = mapped_column(String(10), nullable=False)
    month_end: Mapped[str] = mapped_column(String(10), nullable=False)

    overview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    takeaway: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    keywords: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    trends: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    top_picks: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    category_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    platform_tips: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    topic_clusters: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    action_items: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    content_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    category_count: Mapped[int] = mapped_column(Integer, default=0)

    status: Mapped[str] = mapped_column(String(20), default="PENDING")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc)
    )
