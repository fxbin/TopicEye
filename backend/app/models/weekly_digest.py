"""
Weekly Digest model — AI-generated weekly curated newsletter.
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Optional

from sqlalchemy import String, Text, DateTime, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WeeklyDigest(Base):
    __tablename__ = "weekly_digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Week range identifier, e.g. "2025-W21" or "2025-05-19~2025-05-25"
    week_key: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    # Human-readable date range
    week_label: Mapped[str] = mapped_column(String(50), nullable=False)  # e.g. "5月19日 ~ 5月25日"
    # ISO start / end dates
    week_start: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    week_end: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD

    # ── Generated content fields (all stored as JSON text) ──

    # Weekly overview paragraph
    overview: Mapped[str | None] = mapped_column(Text, nullable=True)
    # One-line takeaway / headline
    takeaway: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Top keywords of the week: JSON array ["AI","产品"]
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Weekly trends: JSON array of {title, desc, color, momentum}
    trends: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Editor's picks — top curated items:
    # JSON array of {rank, title, source, category, reason, score, platforms}
    top_picks: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Category breakdown: JSON object {category: {count, avg_score, top_title}}
    category_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Platform-specific creation tips:
    # JSON object {platform: [tip1, tip2, ...]}
    platform_tips: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Hot topic clusters:
    # JSON array of {name, count, heat, representative_title}
    topic_clusters: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Creator action items:
    # JSON array of {title, angle, difficulty, platform}
    action_items: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Stats ──
    content_count: Mapped[int] = mapped_column(Integer, default=0)
    analyzed_count: Mapped[int] = mapped_column(Integer, default=0)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    category_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Lifecycle ──
    status: Mapped[str] = mapped_column(String(20), default="PENDING")  # PENDING / GENERATING / DONE / ERROR

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
