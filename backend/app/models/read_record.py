"""报告阅读记录模型。

记录用户阅读日报/周刊/月刊的行为（停留时长、阅读次数、时间戳），
作为后期用户行为偏好建模的数据源。

设计：
1. 多态目标：target_type + target_key 复用 Favorite 模式，
   统一适配日报(report_date)/周刊(week_key)/月刊(month_key)三种标识。
2. 幂等 upsert：(user_id, target_type, target_key) 唯一，同篇报告多次阅读累加，
   不插新行。
3. 偏好快照：topic_keywords/category 反范式固化，避免历史报告被覆盖后污染偏好数据。
4. 预留字段：max_progress / depth 第一版不填，待偏好算法接入后启用前端滚动追踪。
5. 保留期：180 天（见 read_record_service.RETENTION_DAYS），由 scheduler 清理。
"""
from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.enum_types import value_enum


class ReadTargetType(enum.StrEnum):
    """阅读记录的目标报告类型。"""

    DAILY_REPORT = "daily_report"
    WEEKLY_DIGEST = "weekly_digest"
    MONTHLY_DIGEST = "monthly_digest"


class ReadDepth(enum.StrEnum):
    """阅读深度分级（派生指标，第一版默认 read）。

    - glanced: 瞥一眼（停留 <5s 或完成度极低）
    - read: 正常阅读
    - deep_read: 深度阅读（高完成度或多次回看）
    """

    GLANCED = "glanced"
    READ = "read"
    DEEP_READ = "deep_read"


class ReadRecord(Base):
    """用户对某篇报告的阅读记录。

    一条记录 = (user_id, target_type, target_key) 三元组，
    同一篇报告多次阅读累加（read_count / accumulated_ms），不新增行。
    """

    __tablename__ = "read_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_type: Mapped[str] = mapped_column(value_enum(ReadTargetType), nullable=False)
    target_key: Mapped[str] = mapped_column(String(64), nullable=False, comment="report_date / week_key / month_key")
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="对应 ORM 主键，便于关联查询")

    # 行为指标
    read_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    accumulated_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="最高阅读完成度 0-100（预留，第一版不填）")
    depth: Mapped[str] = mapped_column(value_enum(ReadDepth), nullable=False, default=ReadDepth.READ)

    # 偏好快照（反范式固化，落库时填充）
    topic_keywords: Mapped[Any | None] = mapped_column(JSON, nullable=True, comment="报告关键词快照数组")
    category: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # 时间戳
    first_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_read_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
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
        UniqueConstraint("user_id", "target_type", "target_key", name="uq_read_record_user_target"),
        Index("ix_read_record_user_type_last_read", "user_id", "target_type", "last_read_at"),
        Index("ix_read_record_user_last_read", "user_id", "last_read_at"),
    )
