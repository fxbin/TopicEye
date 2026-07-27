"""
知乎盐选专栏数据模型。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ZhihuAlbum(Base):
    """知乎盐选专栏/有声书专辑."""

    __tablename__ = "zhihu_albums"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # 知乎业务 ID（用于拼接 URL）
    business_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 排序类型（hottest/newest/monthly_hottest）—— 与 business_id 组成复合唯一约束
    sort_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 标题
    title: Mapped[str] = mapped_column(String(500), nullable=False, index=True)
    # 作者名（第一作者）
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    # 作者简介
    author_desc: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 简介/摘要
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 封面图 URL
    thumb_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    # 所属一级分类名
    category1_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    # 所属二级分类名
    category2_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 文章/章节数（字符串如 "52 篇文章"）
    chapter_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 价格（分，0 表示免费）
    price: Mapped[Integer] = mapped_column(Integer, default=0)
    # 原价（分）
    original_price: Mapped[Integer] = mapped_column(Integer, default=0)
    # 是否独家
    is_exclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    # 是否SVIP专享
    is_svip: Mapped[bool] = mapped_column(Boolean, default=False)
    # 是否已购买
    is_purchased: Mapped[bool] = mapped_column(Boolean, default=False)
    # 上新时间（Unix timestamp）
    online_time: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 上新时间文本（如 "5 月 15 日上新"）
    online_time_text: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 标签（独家/免费等）
    tag: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 订阅类型（svip/free等）
    subscription_name: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # media_type（book/audio等）
    media_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # subcategory（paid_column/audio等）
    subcategory: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # business_line（vip等）
    business_line: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 排序类型（hottest/newest/monthly_hottest）
    sort_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    # 本次排序中的位置（1~N）
    position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 排名变化（与上次快照比，涨则为正，降则为负）
    rank_pos_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 创建时间
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    # 更新时间
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        UniqueConstraint("business_id", "sort_type", name="uq_zhihu_albums_bid_sort"),
        Index("ix_zhihu_albums_sort_pos", "sort_type", "position"),
        Index("ix_zhihu_albums_category1_sort", "category1_name", "sort_type"),
    )

    @property
    def url(self) -> str:
        return f"https://www.zhihu.com/xen/market/remix/paid_column/{self.business_id}"

    @property
    def price_yuan(self) -> str:
        if self.price == 0:
            return "免费"
        return f"¥{self.price / 100:.2f}"

    @property
    def chapter_count(self) -> int | None:
        if not self.chapter_text:
            return None
        import re

        m = re.search(r"(\d+)", self.chapter_text)
        return int(m.group(1)) if m else None


class ZhihuCategory(Base):
    """知乎盐选分类（一级+二级）。"""

    __tablename__ = "zhihu_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    zhihu_id: Mapped[str] = mapped_column(String(50), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    level: Mapped[int] = mapped_column(Integer, default=1)  # 1=一级 2=二级
    parent_id: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    artwork: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_zhihu_cat_parent", "parent_id", "sort"),)


class ZhihuRankSnapshot(Base):
    """知乎榜单快照（用于计算 rank_pos_diff）。"""

    __tablename__ = "zhihu_rank_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    sort_type: Mapped[str] = mapped_column(String(50), nullable=False)
    category1_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category2_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
