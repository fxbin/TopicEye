"""
Repository for Qimao model operations.

封装七猫小说榜单的查询逻辑：
- 榜单概览（按 channel 分组统计各 rank_type 数量）
- 分类列表（从图书数据中提取去重的 category1_name 及数量）
- 图书分页列表（按 channel/rank_type/category 过滤）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.qimao import QimaoBook
from app.repositories.base import BaseRepository


class QimaoRepository(BaseRepository[QimaoBook]):
    """七猫小说榜单图书 CRUD + 聚合查询。"""

    model = QimaoBook

    async def count_books_by_channel_group_by_rank_type(
        self,
        channel: str,
    ) -> list[tuple[str, str, int]]:
        """按 channel 分组统计各 rank_type 的图书数量。

        返回 [(channel, rank_type, count), ...]。
        供 rankings 端点使用。
        """
        result = await self.db.execute(
            select(
                QimaoBook.channel,
                QimaoBook.rank_type,
                func.count(QimaoBook.id).label("count"),
            )
            .where(QimaoBook.channel == channel)
            .group_by(QimaoBook.channel, QimaoBook.rank_type)
        )
        return list(result.all())

    async def list_categories_with_book_count(
        self,
        channel: str | None = None,
    ) -> list[tuple[str, str, int]]:
        """从已有数据中提取去重的 category1_name 及其图书数量。

        返回 [(category1_name, channel, book_count), ...]。
        channel=None 时返回全部 channel 的分类。
        供 categories 端点使用。
        """
        query = (
            select(
                QimaoBook.category1_name,
                QimaoBook.channel,
                func.count(QimaoBook.id).label("book_count"),
            )
            .group_by(QimaoBook.category1_name, QimaoBook.channel)
        )
        if channel:
            query = query.where(QimaoBook.channel == channel)
        result = await self.db.execute(query)
        return list(result.all())

    async def list_books_with_filters(
        self,
        *,
        channel: str,
        rank_type: str,
        category: str | None = None,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[Sequence[QimaoBook], int]:
        """按 channel/rank_type/category 分页查询图书，返回 (items, total)。

        排序：position ASC。与 list_books 端点历史行为等价。
        """
        query = (
            select(QimaoBook)
            .where(QimaoBook.channel == channel, QimaoBook.rank_type == rank_type)
            .order_by(QimaoBook.position)
        )
        if category:
            query = query.where(QimaoBook.category1_name == category)
        count_q = select(func.count()).select_from(query.subquery())
        total = (await self.db.execute(count_q)).scalar() or 0
        query = query.offset(offset).limit(limit)
        result = await self.db.execute(query)
        return result.scalars().all(), int(total)
