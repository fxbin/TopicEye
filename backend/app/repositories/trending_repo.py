"""
Repository for TrendingItem model operations.

服务于 /api/v1/trending 系列端点，封装：
- 带分类/信源/排除信源过滤的列表查询
- 按信源+分类聚合统计
- 全量倒序查询（跨平台共振分析用）
- 按标题模糊搜索（角度推荐用）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.trending import TrendingCategory, TrendingItem, TrendingSource
from app.repositories.base import BaseRepository


class TrendingRepository(BaseRepository[TrendingItem]):
    """TrendingItem 表 CRUD + 趋势雷达专用查询。"""

    model = TrendingItem

    async def list_with_filters(
        self,
        *,
        category: str | None = None,
        source: str | None = None,
        exclude_sources: list[str] | None = None,
        limit: int = 30,
    ) -> Sequence[TrendingItem]:
        """按分类/信源/排除信源过滤，按 source, rank 排序，返回至多 limit*10 条。

        Args:
            category: 分类名（字符串），匹配 TrendingCategory 枚举值，未知值静默忽略
            source: 信源名（字符串），匹配 TrendingSource 枚举值，未知值静默忽略
            exclude_sources: 需排除的信源名列表，未知值静默忽略
            limit: 业务层期望的条数上限；查询层返回 limit*10 以兼容多源场景
        """
        stmt = select(TrendingItem)

        if category:
            try:
                cat_enum = TrendingCategory(category)
                stmt = stmt.where(TrendingItem.category == cat_enum)
            except ValueError:
                pass
        if source:
            try:
                src_enum = TrendingSource(source)
                stmt = stmt.where(TrendingItem.source == src_enum)
            except ValueError:
                pass
        if exclude_sources:
            exclude_enums = []
            for s in exclude_sources:
                try:
                    exclude_enums.append(TrendingSource(s))
                except ValueError:
                    continue
            if exclude_enums:
                stmt = stmt.where(TrendingItem.source.notin_(exclude_enums))

        stmt = stmt.order_by(TrendingItem.source, TrendingItem.rank).limit(limit * 10)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_grouped_by_source_category(self) -> Sequence[tuple]:
        """按 source + category 分组，返回 (source, category, count, last_synced) 元组列表。

        count 为该分组的条目数，last_synced 为该分组最近一次 fetched_at。
        按 category, source 排序。
        """
        stmt = (
            select(
                TrendingItem.source,
                TrendingItem.category,
                func.count(TrendingItem.id).label("count"),
                func.max(TrendingItem.fetched_at).label("last_synced"),
            )
            .group_by(TrendingItem.source, TrendingItem.category)
            .order_by(TrendingItem.category, TrendingItem.source)
        )
        result = await self.db.execute(stmt)
        return result.all()

    async def list_all_ordered_by_source_rank(self) -> Sequence[TrendingItem]:
        """返回全部 TrendingItem，按 source, rank 排序。

        供跨平台共振分析使用，不做 limit。
        """
        stmt = select(TrendingItem).order_by(TrendingItem.source, TrendingItem.rank)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def search_by_title_like(
        self,
        keyword: str,
        *,
        limit: int = 8,
    ) -> Sequence[TrendingItem]:
        """按 title LIKE 搜索，按 rank 升序，返回至多 limit 条。

        Args:
            keyword: 已转义通配符的搜索关键词（调用方负责 %/_ 转义）
            limit: 最多返回条数
        """
        stmt = select(TrendingItem).where(TrendingItem.title.like(keyword)).order_by(TrendingItem.rank).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()
