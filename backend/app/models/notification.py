"""
站内通知模型。
"""

from __future__ import annotations

from datetime import datetime


from sqlalchemy import String, Integer, Boolean, DateTime, Text, ForeignKey, func, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Notification(Base):
    """站内通知。

    target_user_id 决定投递范围：
    - NULL：广播，所有登录用户可见
    - 非 NULL：定向，只对指定 user 可见

    is_read 字段保留（历史兼容）但不再被 service 读取——
    实际"已读"状态由 NotificationRead 表的 per-user 记录控制。
    """

    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)  # success / error / warning / info
    category: Mapped[str] = mapped_column(
        String(50), nullable=False
    )  # fanqie_sync / daily_report / weekly_digest / system
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    # 投递目标用户；NULL = 广播，not null = 定向
    target_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    # 历史兼容字段，新代码不应再读/写
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())

    __table_args__ = (
        Index("ix_notif_read", "is_read"),
        Index("ix_notif_cat", "category"),
        Index("ix_notif_target", "target_user_id"),
    )


class NotificationRead(Base):
    """Per-user 已读记录。

    复合主键 (user_id, notification_id) 避免重复。
    """

    __tablename__ = "notification_reads"

    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    notification_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("notifications.id", ondelete="CASCADE"), primary_key=True
    )
    read_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=func.now())

    __table_args__ = (Index("ix_notification_reads_user", "user_id"),)
