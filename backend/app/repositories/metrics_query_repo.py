"""
Prometheus /metrics 端点专用聚合查询 repo。

跨 Source / ContentItem / AiAnalysis / JobExecutionLog / Notification
五个 model 做 group-by 与 count 聚合，返回值均为 (label_value, count) 元组列表
或单一计数。

不继承 BaseRepository，因为查询跨多个 model 且不写。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.notification import Notification
from app.models.scheduled_job import JobExecutionLog
from app.models.source import Source


class MetricsQueryRepository:
    """Prometheus /metrics 端点的业务数据层聚合查询（非 BaseRepository 子类）。

    Usage:
        repo = MetricsQueryRepository(db)
        for status, count in await repo.count_sources_by_status():
            ...
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def count_sources_by_status(self) -> Sequence[tuple]:
        """按 Source.status 分组计数，返回 (status, count) 元组列表。"""
        result = await self.db.execute(select(Source.status, func.count()).group_by(Source.status))
        return result.all()

    async def count_content_by_status(self) -> Sequence[tuple]:
        """按 ContentItem.status 分组计数，返回 (status, count) 元组列表。"""
        result = await self.db.execute(select(ContentItem.status, func.count()).group_by(ContentItem.status))
        return result.all()

    async def count_recent_content(self, cutoff: datetime) -> int:
        """统计 crawled_at >= cutoff 的内容数。"""
        count = await self.db.scalar(
            select(func.count()).select_from(ContentItem).where(ContentItem.crawled_at >= cutoff)
        )
        return count or 0

    async def count_analyses(self) -> int:
        """统计 AiAnalysis 总数。"""
        count = await self.db.scalar(select(func.count()).select_from(AiAnalysis))
        return count or 0

    async def count_job_runs_by_status_since(self, cutoff: datetime) -> Sequence[tuple]:
        """按 JobExecutionLog.status 分组统计 started_at >= cutoff 的运行数。

        返回 (status, count) 元组列表。
        """
        result = await self.db.execute(
            select(JobExecutionLog.status, func.count())
            .where(JobExecutionLog.started_at >= cutoff)
            .group_by(JobExecutionLog.status)
        )
        return result.all()

    async def count_notifications(self) -> int:
        """统计 Notification 总数。"""
        count = await self.db.scalar(select(func.count()).select_from(Notification))
        return count or 0
