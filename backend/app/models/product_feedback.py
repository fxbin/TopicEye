from __future__ import annotations

import enum
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enum_types import value_enum


class IssueFeedbackSeverity(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class IssueFeedbackStatus(str, enum.Enum):
    open = "open"
    triaged = "triaged"
    in_progress = "in_progress"
    fixed = "fixed"
    closed = "closed"


class ProductUpdateKind(str, enum.Enum):
    roadmap = "roadmap"
    release = "release"
    fix = "fix"
    improvement = "improvement"


class ProductUpdateStatus(str, enum.Enum):
    planned = "planned"
    in_progress = "in_progress"
    shipped = "shipped"


class IssueFeedback(Base):
    __tablename__ = "issue_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    area: Mapped[str] = mapped_column(String(80), nullable=False, default="general")
    severity: Mapped[str] = mapped_column(
        value_enum(IssueFeedbackSeverity), nullable=False, default=IssueFeedbackSeverity.medium
    )
    status: Mapped[str] = mapped_column(
        value_enum(IssueFeedbackStatus), nullable=False, default=IssueFeedbackStatus.open
    )
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fixed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User")

    __table_args__ = (
        Index("ix_issue_feedback_user_created", "user_id", "created_at"),
        Index("ix_issue_feedback_status_created", "status", "created_at"),
        Index("ix_issue_feedback_severity_created", "severity", "created_at"),
    )


class ProductUpdate(Base):
    """1 个版本 = 1 行; items 是 JSON 数组, 每项含 {title, description, kind}.

    title/description/kind 三个旧字段保留为 nullable, 仅用于历史数据兼容;
    新写入路径用 items, 旧字段不再读。
    """

    __tablename__ = "product_updates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        value_enum(ProductUpdateStatus), nullable=False, default=ProductUpdateStatus.planned
    )
    target_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    shipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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

    # 历史/兼容字段 (新代码不读)
    title: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    kind: Mapped[Optional[str]] = mapped_column(value_enum(ProductUpdateKind), nullable=True)

    created_by = relationship("User")

    __table_args__ = (
        Index("ix_product_updates_status_created", "status", "created_at"),
        Index("ix_product_updates_shipped_at", "shipped_at"),
        Index("ix_product_updates_version", "version"),
    )
