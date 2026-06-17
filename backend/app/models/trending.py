"""
TrendingSnapshot — 趋势雷达历史快照。

每天凌晨自动保存一份全量快照，保留15天。
用于：对比昨日排名、判断话题趋势（上升/下降/新上榜）。

和 TrendingItem 的区别：
- TrendingItem：实时数据，每次同步替换
- TrendingSnapshot：历史存档，永久保留15天
"""

from __future__ import annotations

import enum
from datetime import datetime, date, timezone, UTC
from typing import Optional, List

from sqlalchemy import String, Integer, DateTime, Date, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base
from app.models.enum_types import value_enum


class TrendingSource(enum.StrEnum):
    WEIBO = "weibo"
    BAIDU = "baidu"
    DOUYIN = "douyin"
    TOUTIAO = "toutiao"
    ZHIHU = "zhihu"
    HUPU = "hupu"
    TIEBA = "tieba"
    ITHOME = "ithome"
    KR36 = "36kr"
    BILIBILI = "bilibili"
    JUEJIN = "juejin"
    SSPAI = "sspai"
    HACKERNEWS = "hackernews"
    GITHUB = "github"
    WALLSTREETCN = "wallstreetcn"
    CLS = "cls"
    XUEQIU = "xueqiu"
    EASTMONEY = "eastmoney"
    DOUBAN = "douban"
    IQIYI = "iqiyi"
    NETEASE = "netease"
    V2EX = "v2ex"
    SOHU = "sohu"
    # 网文平台榜单（黑岩/点众，公开 API）
    HEIYAN = "heiyan"
    ISHUGUI = "ishugui"


class TrendingCategory(enum.StrEnum):
    HOT = "hot"
    TECH = "tech"
    FINANCE = "finance"
    ENTERTAINMENT = "entertainment"
    COMMUNITY = "community"
    WEBNOVEL = "webnovel"


class TrendingItem(Base):
    __tablename__ = "trending_items"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(value_enum(TrendingSource), nullable=False, index=True)
    category: Mapped[str] = mapped_column(value_enum(TrendingCategory), nullable=False, index=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    hot_value: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    hot_value_raw: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    trend: Mapped[str | None] = mapped_column(String(20), nullable=True)  # up/down/new/stable
    cover_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    batch_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)


class TrendingSnapshot(Base):
    """
    趋势雷达定时快照。
    每天 4 个快照点（08/12/18/22），保留 7 天。
    用 (snapshot_date, snapshot_hour, source) 唯一标识一份快照。
    """

    __tablename__ = "trending_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    snapshot_hour: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # 8/12/18/22
    source: Mapped[str] = mapped_column(value_enum(TrendingSource), nullable=False)
    category: Mapped[str] = mapped_column(String(20), nullable=False, default="hot")
    items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
