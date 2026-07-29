"""Canonical event groups and their non-canonical content members."""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enum_types import value_enum

if TYPE_CHECKING:
    from app.models.content import ContentItem
    from app.models.user import User


class EventStatus(enum.StrEnum):
    SHADOW = "shadow"
    ACTIVE = "active"
    ARCHIVED = "archived"


class EventRelationType(enum.StrEnum):
    DUPLICATE = "duplicate"
    CORROBORATION = "corroboration"
    UPDATE = "update"


class EventReviewStatus(enum.StrEnum):
    PENDING = "pending"
    AUTO = "auto"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


class ContentEventGroup(Base):
    """Stable owner of an event canonical and its lifecycle metadata."""

    __tablename__ = "content_event_groups"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
    )
    canonical_content_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="RESTRICT"),
        nullable=False,
    )
    canonical_policy: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="earliest",
        server_default="earliest",
    )
    canonical_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    canonical_locked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=false(),
    )
    canonical_locked_by_user_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    canonical_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    first_occurrence_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    last_occurrence_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        value_enum(EventStatus),
        nullable=False,
        default=EventStatus.ACTIVE,
        server_default=EventStatus.ACTIVE.value,
    )
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    classifier_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "canonical_content_id",
            name="uq_content_event_groups_canonical_content",
        ),
        CheckConstraint(
            "first_occurrence_at <= last_occurrence_at",
            name="ck_content_event_groups_occurrence_order",
        ),
        CheckConstraint(
            "canonical_policy IN ('earliest', 'manual')",
            name="ck_content_event_groups_canonical_policy",
        ),
        CheckConstraint(
            "status IN ('shadow', 'active', 'archived')",
            name="ck_content_event_groups_status",
        ),
        CheckConstraint(
            "version >= 1",
            name="ck_content_event_groups_version",
        ),
        Index(
            "ix_content_event_groups_owner_last",
            "owner_user_id",
            last_occurrence_at.desc(),
        ),
        Index("ix_content_event_groups_locked", "canonical_locked"),
    )

    owner: Mapped[User | None] = relationship(
        foreign_keys=[owner_user_id],
    )
    canonical_locked_by: Mapped[User | None] = relationship(
        foreign_keys=[canonical_locked_by_user_id],
    )
    canonical_content: Mapped[ContentItem] = relationship(
        foreign_keys=[canonical_content_id],
    )
    members: Mapped[list[ContentEventMember]] = relationship(
        back_populates="event_group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ContentEventMember(Base):
    """A non-canonical content item classified into one event group."""

    __tablename__ = "content_event_members"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    event_group_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content_event_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    content_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
    )
    relation_type: Mapped[str] = mapped_column(
        value_enum(EventRelationType),
        nullable=False,
        default=EventRelationType.DUPLICATE,
        server_default=EventRelationType.DUPLICATE.value,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    match_method: Mapped[str] = mapped_column(String(50), nullable=False)
    detector_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(
        value_enum(EventReviewStatus),
        nullable=False,
        default=EventReviewStatus.PENDING,
        server_default=EventReviewStatus.PENDING.value,
    )
    matched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("content_id", name="uq_content_event_members_content"),
        UniqueConstraint(
            "event_group_id",
            "content_id",
            name="uq_content_event_members_group_content",
        ),
        CheckConstraint(
            "relation_type IN ('duplicate', 'corroboration', 'update')",
            name="ck_content_event_members_relation_type",
        ),
        CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="ck_content_event_members_confidence",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'auto', 'confirmed', 'rejected')",
            name="ck_content_event_members_review_status",
        ),
        Index(
            "ix_content_event_members_group_relation_matched",
            "event_group_id",
            "relation_type",
            "matched_at",
        ),
    )

    event_group: Mapped[ContentEventGroup] = relationship(
        back_populates="members",
    )
    content: Mapped[ContentItem] = relationship(
        foreign_keys=[content_id],
    )
