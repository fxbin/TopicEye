"""Durable audit and fencing state for incremental event normalization."""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enum_types import value_enum


class EventNormalizationMode(enum.StrEnum):
    SHADOW = "shadow"
    WRITE = "write"


class EventNormalizationRunStatus(enum.StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class ContentEventNormalizationLease(Base):
    """One cross-process lease per public/private owner scope."""

    __tablename__ = "content_event_normalization_leases"

    scope_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    fencing_token: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    lease_token: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "fencing_token >= 0",
            name="ck_content_event_normalization_leases_fence",
        ),
        Index(
            "ix_content_event_normalization_leases_expiry",
            "lease_expires_at",
        ),
    )


class ContentEventNormalizationRun(Base):
    """Bounded prediction audit plus the final result of one idempotent pass."""

    __tablename__ = "content_event_normalization_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False)
    mode: Mapped[str] = mapped_column(
        value_enum(EventNormalizationMode),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        value_enum(EventNormalizationRunStatus),
        nullable=False,
        default=EventNormalizationRunStatus.RUNNING,
        server_default=EventNormalizationRunStatus.RUNNING.value,
    )
    fencing_token: Mapped[int] = mapped_column(Integer, nullable=False)
    lease_token: Mapped[str] = mapped_column(String(64), nullable=False)
    window_hours: Mapped[int] = mapped_column(Integer, nullable=False)
    classifier_version: Mapped[str] = mapped_column(String(100), nullable=False)
    scanned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    matched_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    pending_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    standalone_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    created_member_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    llm_call_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    predictions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    model_routes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "scope_key",
            "idempotency_key",
            name="uq_content_event_normalization_runs_scope_key",
        ),
        CheckConstraint(
            "mode IN ('shadow', 'write')",
            name="ck_content_event_normalization_runs_mode",
        ),
        CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_content_event_normalization_runs_status",
        ),
        CheckConstraint(
            "fencing_token >= 1",
            name="ck_content_event_normalization_runs_fence",
        ),
        CheckConstraint(
            "window_hours >= 1",
            name="ck_content_event_normalization_runs_window",
        ),
        Index(
            "ix_content_event_normalization_runs_scope_started",
            "scope_key",
            started_at.desc(),
        ),
        Index(
            "ix_content_event_normalization_runs_status_started",
            "status",
            started_at.desc(),
        ),
    )
