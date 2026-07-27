from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enum_types import value_enum
from app.models.user import User


class FavoriteTargetType(enum.StrEnum):
    CONTENT = "content"
    BOOK = "book"
    SOURCE = "source"
    TREND = "trend"
    AUTHOR = "author"
    TOPIC_GROUP = "topic_group"


class FavoriteStatus(enum.StrEnum):
    INBOX = "inbox"
    RESEARCHING = "researching"
    DRAFTING = "drafting"
    ARCHIVED = "archived"


class FavoriteItem(Base):
    __tablename__ = "favorite_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(value_enum(FavoriteTargetType), nullable=False)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_key: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    collection_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(value_enum(FavoriteStatus), nullable=False, default=FavoriteStatus.INBOX)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship()

    __table_args__ = (
        UniqueConstraint("user_id", "target_type", "target_key", name="uq_favorite_user_target"),
        Index("ix_favorite_items_user_type_created", "user_id", "target_type", "created_at"),
        Index("ix_favorite_items_user_status_created", "user_id", "status", "created_at"),
        Index("ix_favorite_items_user_status_position", "user_id", "status", "position"),
    )
