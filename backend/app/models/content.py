from __future__ import annotations
from typing import Optional
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, JSON, Boolean, Float, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enum_types import value_enum


class ContentStatus(str, enum.Enum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    ERROR = "error"


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    source_type: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True, comment="冗余 source.owner_user_id；NULL=公共内容池"
    )
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    cover_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tags: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(value_enum(ContentStatus), nullable=False, default=ContentStatus.PENDING)
    is_favorited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Topic clustering fields
    topic_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("topic_groups.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_of: Mapped[Optional[int]] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
        comment="Points to canonical item if duplicate",
    )
    similarity_score: Mapped[Optional[float]] = mapped_column(
        Float, default=0.0, comment="Similarity score to group representative"
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

    __table_args__ = (
        Index("ix_content_items_owner", "owner_user_id"),
        Index("ix_content_items_owner_status", "owner_user_id", "status"),
        UniqueConstraint("source_id", "content_hash", name="uq_content_items_source_hash"),
    )

    source: Mapped[Optional["Source"]] = relationship(back_populates="contents")
    metrics: Mapped[list["ContentMetrics"]] = relationship(back_populates="content", cascade="all, delete-orphan")
    analyses: Mapped[list["AiAnalysis"]] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="AiAnalysis.created_at, AiAnalysis.id",
    )
    topic: Mapped[Optional["TopicGroup"]] = relationship(back_populates="items", foreign_keys=[topic_id])
