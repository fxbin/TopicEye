"""
Repository for JobExecutionLog model operations.

封装 /stats/jobs 端点的 6 个聚合查询：
- by_status 分组计数
- duration 聚合（avg/max）
- by_job_key 每个 key 的运行数
- 每个 job_key 的 success_count（per-key 查询）
- 每个 job_key 的最后一条记录
- per-job_key avg_duration 聚合
- recent_failures 最近失败

所有方法仅返回原始 row，业务格式化（success_rate 计算、isoformat 等）
由 api 层负责，保持行为等价。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.scheduled_job import JobExecutionLog


class JobExecutionLogRepository:
    """JobExecutionLog 聚合查询（非 BaseRepository 子类，只做投影聚合）。

    Usage:
        repo = JobExecutionLogRepository(db)
        status_rows = await repo.count_by_status_since(cutoff=cutoff, job_key=job_key)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def count_by_status_since(
        self,
        *,
        cutoff: datetime,
        job_key: str | None = None,
    ) -> Sequence[tuple]:
        """按 status 分组计数，返回 [(status, count), ...]。"""
        stmt = (
            select(JobExecutionLog.status, func.count().label("count"))
            .where(JobExecutionLog.started_at >= cutoff)
            .group_by(JobExecutionLog.status)
        )
        if job_key:
            stmt = stmt.where(JobExecutionLog.job_key == job_key)
        result = await self.db.execute(stmt)
        return result.all()

    async def aggregate_duration_since(
        self,
        *,
        cutoff: datetime,
        job_key: str | None = None,
    ) -> tuple:
        """返回 (avg_dur, max_dur) 聚合行，duration_ms 为 NULL 的行不参与。"""
        stmt = select(
            func.avg(JobExecutionLog.duration_ms).label("avg_dur"),
            func.max(JobExecutionLog.duration_ms).label("max_dur"),
        ).where(
            JobExecutionLog.started_at >= cutoff,
            JobExecutionLog.duration_ms.isnot(None),
        )
        if job_key:
            stmt = stmt.where(JobExecutionLog.job_key == job_key)
        result = await self.db.execute(stmt)
        return result.one()

    async def count_runs_per_job_key_since(
        self,
        *,
        cutoff: datetime,
        job_key: str | None = None,
    ) -> Sequence[tuple]:
        """按 job_key 分组返回运行数，按 count 降序。返回 [(job_key, runs), ...]。"""
        stmt = (
            select(
                JobExecutionLog.job_key,
                func.count().label("runs"),
            )
            .where(JobExecutionLog.started_at >= cutoff)
            .group_by(JobExecutionLog.job_key)
            .order_by(func.count().desc())
        )
        if job_key:
            stmt = stmt.where(JobExecutionLog.job_key == job_key)
        result = await self.db.execute(stmt)
        return result.all()

    async def count_success_for_job_key(
        self,
        *,
        job_key: str,
        cutoff: datetime,
    ) -> int:
        """统计指定 job_key 在 cutoff 后的 SUCCESS 数量。"""
        stmt = select(func.count()).where(
            JobExecutionLog.job_key == job_key,
            JobExecutionLog.started_at >= cutoff,
            JobExecutionLog.status == "SUCCESS",
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def get_last_run_for_job_key(self, job_key: str) -> tuple | None:
        """返回指定 job_key 的最近一条记录的 (status, started_at, duration_ms, error_message)。"""
        stmt = (
            select(
                JobExecutionLog.status,
                JobExecutionLog.started_at,
                JobExecutionLog.duration_ms,
                JobExecutionLog.error_message,
            )
            .where(JobExecutionLog.job_key == job_key)
            .order_by(JobExecutionLog.started_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.one_or_none()

    async def aggregate_avg_duration_per_job_key_since(
        self,
        *,
        cutoff: datetime,
    ) -> Sequence[tuple]:
        """按 job_key 分组返回 avg(duration_ms)。返回 [(job_key, avg_dur), ...]。"""
        stmt = (
            select(
                JobExecutionLog.job_key,
                func.avg(JobExecutionLog.duration_ms).label("avg_dur"),
            )
            .where(
                JobExecutionLog.started_at >= cutoff,
                JobExecutionLog.duration_ms.isnot(None),
            )
            .group_by(JobExecutionLog.job_key)
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def list_recent_failures_since(
        self,
        *,
        cutoff: datetime,
        job_key: str | None = None,
        limit: int = 10,
    ) -> Sequence[tuple]:
        """返回最近的失败/超时记录，按 started_at 倒序。

        返回 [(job_key, status, started_at, duration_ms, error_message), ...]。
        """
        stmt = (
            select(
                JobExecutionLog.job_key,
                JobExecutionLog.status,
                JobExecutionLog.started_at,
                JobExecutionLog.duration_ms,
                JobExecutionLog.error_message,
            )
            .where(
                JobExecutionLog.started_at >= cutoff,
                JobExecutionLog.status.in_(["FAILED", "TIMEOUT"]),
            )
            .order_by(JobExecutionLog.started_at.desc())
            .limit(limit)
        )
        if job_key:
            stmt = stmt.where(JobExecutionLog.job_key == job_key)
        result = await self.db.execute(stmt)
        return result.all()
