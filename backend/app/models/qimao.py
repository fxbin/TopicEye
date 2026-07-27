"""
七猫小说模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QimaoBook(Base):
    """七猫小说榜单图书。"""

    __tablename__ = "qimao_books"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    book_id: Mapped[str] = mapped_column(String(50), nullable=False)  # 同书可出现在不同榜单
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    author: Mapped[str] = mapped_column(String(200), nullable=False)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    category1_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    category2_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    thumb_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    words_num: Mapped[str | None] = mapped_column(String(50), nullable=True)  # "859.29万字"
    collect_count: Mapped[float | None] = mapped_column(Integer, nullable=True)  # 收藏数
    latest_chapter_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latest_chapter_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    update_time: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 1=连载
    is_over: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0=未完结
    is_new: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 0/1
    is_continue_top: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 霸榜
    index_change: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 排名变化
    surge_rank: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 飙升排名
    bonus: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 奖励

    # 榜单维度
    channel: Mapped[Literal["boy", "girl"]] = mapped_column(String(10), nullable=False)  # 男/女
    rank_type: Mapped[Literal["hot", "new", "over", "collect", "update"]] = mapped_column(String(20), nullable=False)
    date_type: Mapped[str] = mapped_column(String(10), nullable=False)  # ""/"day"/"month"
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 榜单内排名

    crawled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_qimao_channel_rank", "channel", "rank_type"),
        Index("ix_qimao_book", "book_id"),
    )
