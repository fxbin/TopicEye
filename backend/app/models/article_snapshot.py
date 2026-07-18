"""Reader-mode snapshots for content items.

Snapshots deliberately store extracted text rather than third-party HTML.  This
keeps the reader surface free of executable markup and lets a user see when the
source was fetched without pretending it is a live copy of the publisher page.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ArticleSnapshot(Base):
    __tablename__ = "article_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("content_items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    canonical_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    fetch_status: Mapped[str] = mapped_column(String(24), nullable=False, default="ready")
    extraction_method: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    byline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    text_content: Mapped[str] = mapped_column(Text, nullable=False)
    # Kept alongside the compatibility text field so the reader can preserve
    # headings, quotes and lists without ever rendering publisher HTML.
    content_blocks: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # 中文翻译缓存（首次翻译后落库，空表示未翻译或原文已是中文）
    text_content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_blocks_zh: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    reading_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    content: Mapped["ContentItem"] = relationship(back_populates="reader_snapshot")

    __table_args__ = (
        Index("ix_article_snapshots_expires_at", "expires_at"),
        Index("ix_article_snapshots_fetch_status", "fetch_status"),
    )
