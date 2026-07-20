"""
信源健康聚合查询 repo。

专门服务于 /stats/sources-health 端点的两类查询：
1. 主查询：source + 每源内容总数（子查询 + LEFT JOIN）
2. 副查询：单源 24h 新增内容数（保留原 N+1 行为，不在此优化）

不继承 BaseRepository，因为返回值不是单一 ORM 对象，
而是 (Source, int) 元组列表 / int 计数。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.source import Source


class SourceHealthRepository:
    """信源健康聚合查询（非 BaseRepository 子类）。

    Usage:
        repo = SourceHealthRepository(db)
        rows = await repo.list_sources_with_content_count(status_filter, limit)
        for source, content_count in rows:
            recent = await repo.count_recent_content(source.id, recent_cutoff_dt)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_sources_with_content_count(
        self,
        status_filter: str | None,
        limit: int,
    ) -> Sequence[tuple[Source, int]]:
        """返回 (source, total_content_count) 列表，按 last_sync_at 倒序。

        子查询统计每个 source 的内容总数，LEFT JOIN 到 Source，
        避免无内容的 source 被过滤掉。可选按 status 过滤。

        Args:
            status_filter: 按 Source.status 过滤，None 表示不过滤
            limit: 最多返回的 source 数量

        Returns:
            元组列表，每个元组为 (Source 对象, 该 source 的内容总数)
        """
        total_subq = (
            select(ContentItem.source_id, func.count().label("cnt"))
            .group_by(ContentItem.source_id)
            .subquery()
        )

        stmt = select(
            Source,
            func.coalesce(total_subq.c.cnt, 0).label("content_count"),
        ).outerjoin(total_subq, total_subq.c.source_id == Source.id)

        if status_filter:
            stmt = stmt.where(Source.status == status_filter)

        stmt = stmt.order_by(desc(Source.last_sync_at)).limit(limit)

        result = await self.db.execute(stmt)
        return result.all()

    async def count_recent_content(
        self,
        source_id: int,
        recent_cutoff: datetime,
    ) -> int:
        """统计指定 source 在 cutoff 时间之后新增的内容数。

        保留原 endpoint 的 N+1 行为（每源单独查一次），
        不在此优化为批量查询，避免混合关注点。

        Args:
            source_id: 信源 ID
            recent_cutoff: 时间下限（含），早于此时间的内容不计

        Returns:
            内容数，无匹配时返回 0
        """
        count = await self.db.scalar(
            select(func.count())
            .select_from(ContentItem)
            .where(
                ContentItem.source_id == source_id,
                ContentItem.crawled_at >= recent_cutoff,
            )
        )
        return count or 0
