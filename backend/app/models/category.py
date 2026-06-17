"""
Category model — LLM-driven dynamic content classification.

Stores both seed (manually created) and auto-discovered categories.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    keywords: Mapped[Optional[str]] = mapped_column(
        Text, nullable=True, comment="Comma-separated keywords for fallback matching"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_auto_created: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="True if discovered by LLM"
    )
    content_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="Denormalized count for sorting"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
