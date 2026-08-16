"""日报选题标记模型。

用户在日报选题卡上的操作（写这个/观察/跳过），持久化到 DB。
用于：
1. 日报页面恢复标记状态（刷新不丢失）
2. 周报追踪「连续在榜 N 天」的选题
3. 影响后续推荐权重
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PickMark(Base):
    """用户对日报选题的标记。

    一次标记 = (user_id, report_date, pick_title) 三元组，
    同一天同一个选题只能有一个标记（更新而非新增）。
    """

    __tablename__ = "pick_marks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    report_date: Mapped[str] = mapped_column(Date, nullable=False, comment="日报日期 YYYY-MM-DD")
    pick_title: Mapped[str] = mapped_column(Text, nullable=False, comment="选题标题（标记唯一键之一）")
    action: Mapped[str] = mapped_column(Text, nullable=False, comment="write / watch / skip")
    pick_category: Mapped[str | None] = mapped_column(Text, nullable=True)
    pick_source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
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
        UniqueConstraint("user_id", "report_date", "pick_title", name="uq_pick_mark_user_date_title"),
        Index("ix_pick_mark_user_date", "user_id", "report_date"),
        Index("ix_pick_mark_action", "user_id", "action"),
    )
