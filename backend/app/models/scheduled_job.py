"""
Job execution tracking models.

Two tables:
  - scheduled_jobs: task config (name, cron, enabled, timeout …)
  - job_execution_logs: every run (start, end, status, duration, result)
"""

from datetime import datetime, timezone, UTC
from typing import Optional

from sqlalchemy import (
    String,
    Integer,
    Boolean,
    DateTime,
    Text,
    Index,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, comment="唯一任务标识")
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="显示名称")
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, default="cron", comment="cron / interval")
    cron_expr: Mapped[str | None] = mapped_column(String(100), nullable=True, comment="cron 表达式")
    interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="interval 间隔秒数")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_scheduled_jobs_enabled", "enabled"),)

    def __repr__(self) -> str:
        return f"<ScheduledJob {self.job_key}>"


class JobExecutionLog(Base):
    __tablename__ = "job_execution_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_key: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="RUNNING / SUCCESS / FAILED / TIMEOUT / SKIPPED"
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="执行耗时(毫秒)")
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="成功时输出摘要")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败时错误信息")
    trigger_type: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="scheduler / manual")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_job_exec_logs_job_key_started", "job_key", "started_at"),)

    def __repr__(self) -> str:
        return f"<JobExecutionLog {self.job_key} {self.status}>"
