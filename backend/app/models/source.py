from __future__ import annotations
from typing import Optional
import enum
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Text, DateTime, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base
from app.models.enum_types import value_enum


class SourceType(str, enum.Enum):
    RSS = "RSS"
    RSSHub = "RSSHub"
    REDDIT = "Reddit"
    WEBSITE = "网站"
    WECHAT = "公众号"
    XIAOHONGSHU = "小红书"
    X = "X"
    TWITTER_RSS = "TwitterRSS"
    YOUTUBE = "YouTube"
    PODCAST = "Podcast"
    NEWSLETTER = "Newsletter"
    ZHIHU = "Zhihu"
    BILIBILI = "B站"
    DOUYIN_HOT = "DouyinHot"
    API = "API"
    CUSTOM = "自定义"


class SourceStatus(str, enum.Enum):
    ACTIVE = "active"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


class Source(Base):
    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="system")
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(value_enum(SourceType), nullable=False, default=SourceType.RSS)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    keyword: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    platform: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(value_enum(SourceStatus), nullable=False, default=SourceStatus.ACTIVE)
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    fetch_interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # ── Conditional request state (HTTP If-None-Match / If-Modified-Since) ──
    etag: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    last_modified: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    enabled: Mapped[bool] = mapped_column(default=True)
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
        Index("ix_sources_owner", "owner_user_id"),
        Index("ix_sources_owner_enabled", "owner_user_id", "enabled"),
    )

    contents: Mapped[list["ContentItem"]] = relationship(back_populates="source", cascade="all, delete-orphan")
