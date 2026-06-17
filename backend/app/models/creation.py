"""
创作方案模型。

之前 generate_creation_plan 只返回 LLM dict，重新生成就丢历史。
本表持久化历史方案，便于：
- 用户回看自己生成过的内容
- 重新生成时拉历史对比
- 后续做协作 / 分享 / 导出
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CreationPlan(Base):
    """用户为某个 ContentItem 在指定 platform 上生成的创作方案。"""

    __tablename__ = "creation_plans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)  # xiaohongshu / short_video / wechat
    platform_name: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 冗余显示名
    content_title_snapshot: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="内容删除后仍能展示历史方案"
    )
    # LLM 生成的完整 plan（titles / structure / scenes / outline 等）
    plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    # 可选的 error 字段，标记生成失败的方案（保留作日志）
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_creation_plans_user", "user_id"),
        Index("ix_creation_plans_user_platform", "user_id", "platform"),
        Index("ix_creation_plans_content", "content_id"),
    )
