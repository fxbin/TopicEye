"""
番茄小说榜单数据模型。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class FanqieCategory(Base):
    """番茄分类。"""

    __tablename__ = "fanqie_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fanqie_id: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)  # "1141"
    name: Mapped[str] = mapped_column(String(100), nullable=False)  # "西方奇幻"
    group: Mapped[str] = mapped_column(String(20), nullable=False)  # "male" / "female"
    display_order: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), onupdate=func.now())

    __table_args__ = (Index("ix_fanqie_cat_group", "group"),)


class FanqieBook(Base):
    """番茄榜单图书。"""

    __tablename__ = "fanqie_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)  # "7320218217488600126"
    book_name: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str] = mapped_column(String(200))
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    category_id: Mapped[str] = mapped_column(String(20), nullable=False)  # fanqie_id like "1141"
    category_name: Mapped[str] = mapped_column(String(100), nullable=True)
    thumb_uri: Mapped[str | None] = mapped_column(String(1000))
    read_count: Mapped[str | None] = mapped_column(String(50))  # "417817"
    word_number: Mapped[str | None] = mapped_column(String(50))  # "2626537"
    last_chapter_title: Mapped[str | None] = mapped_column(String(500))
    last_chapter_update_time: Mapped[int | None] = mapped_column(Integer)
    current_pos: Mapped[int] = mapped_column(Integer, default=0)  # 榜单排名
    rank_type: Mapped[str] = mapped_column(
        String(30), nullable=False
    )  # male_reading / male_new / female_reading / female_new
    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    # 四个榜单各一个 pos
    male_reading_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    male_new_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_reading_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    female_new_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank_pos_diff: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 排名变化（正=上升，负=下降）

    __table_args__ = (
        Index("ix_fanqie_book_ranktype", "rank_type"),
        Index("ix_fanqie_book_cat", "category_id"),
    )


class FanqieRankSnapshot(Base):
    """番茄排名历史快照——每天存一份，用于排名变化分析。"""

    __tablename__ = "fanqie_rank_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[str] = mapped_column(String(10), nullable=False)  # "2026-05-25"
    book_id: Mapped[str] = mapped_column(String(50), nullable=False)
    book_name: Mapped[str] = mapped_column(String(500), nullable=False)
    rank_type: Mapped[str] = mapped_column(String(30), nullable=False)  # male_reading / male_new / ...
    category_id: Mapped[str] = mapped_column(String(20), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 当日排名
    read_count: Mapped[str | None] = mapped_column(String(50))
    word_number: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("ix_snap_date_type", "snapshot_date", "rank_type"),
        Index("ix_snap_book", "book_id"),
    )
