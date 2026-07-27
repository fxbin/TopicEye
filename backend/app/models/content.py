from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.enum_types import value_enum

if TYPE_CHECKING:
    from app.models.ai_analysis import AiAnalysis
    from app.models.article_snapshot import ArticleSnapshot
    from app.models.metrics import ContentMetrics
    from app.models.source import Source
    from app.models.topic import TopicGroup


class ContentStatus(enum.StrEnum):
    PENDING = "pending"
    ANALYZING = "analyzing"
    ANALYZED = "analyzed"
    ERROR = "error"


class ContentItem(Base):
    __tablename__ = "content_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    source_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="SET NULL"), nullable=True
    )
    source_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(100), nullable=True)
    owner_user_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="冗余 source.owner_user_id；NULL=公共内容池"
    )
    author: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crawled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    status: Mapped[str] = mapped_column(value_enum(ContentStatus), nullable=False, default=ContentStatus.PENDING)
    is_favorited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # LLM 规则过滤层（参照 content-signal-radar 的 lowSignalPenalty 设计）
    # skip_analysis=True 时不进 LLM 队列（不入 claim_pending），但仍入库保留
    skip_analysis: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    skip_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Topic clustering fields
    topic_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("topic_groups.id", ondelete="SET NULL"), nullable=True
    )
    duplicate_of: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="SET NULL"),
        nullable=True,
        comment="Points to canonical item if duplicate",
    )
    similarity_score: Mapped[float | None] = mapped_column(
        Float, default=0.0, comment="Similarity score to group representative"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_content_items_owner", "owner_user_id"),
        Index("ix_content_items_owner_status", "owner_user_id", "status"),
        UniqueConstraint("source_id", "content_hash", name="uq_content_items_source_hash"),
    )

    source: Mapped[Source | None] = relationship(back_populates="contents")
    metrics: Mapped[list[ContentMetrics]] = relationship(back_populates="content", cascade="all, delete-orphan")
    analyses: Mapped[list[AiAnalysis]] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        order_by="AiAnalysis.created_at, AiAnalysis.id",
    )
    topic: Mapped[TopicGroup | None] = relationship(back_populates="items", foreign_keys=[topic_id])
    reader_snapshot: Mapped[ArticleSnapshot | None] = relationship(
        back_populates="content",
        cascade="all, delete-orphan",
        uselist=False,
    )
