"""
Repository for Fanqie model operations.

封装番茄小说榜单的查询逻辑：
- 分类列表（按 group + display_order 排序）
- 四大榜单查询（按 rank_type + current_pos 排序）
- 分类下书单查询（按 pos 字段排序）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.models.fanqie import FanqieBook, FanqieCategory
from app.repositories.base import BaseRepository


class FanqieRepository(BaseRepository[FanqieBook]):
    """番茄小说榜单图书 CRUD + 分类/榜单查询。"""

    model = FanqieBook

    async def list_categories_ordered(self) -> Sequence[FanqieCategory]:
        """返回所有番茄分类，按 group 和 display_order 排序。

        与 list_categories 端点历史行为等价。
        """
        result = await self.db.execute(
            select(FanqieCategory).order_by(
                FanqieCategory.group,
                FanqieCategory.display_order,
            )
        )
        return result.scalars().all()

    async def list_books_by_rank_type(self, rank_type: str, limit: int = 100) -> Sequence[FanqieBook]:
        """按榜单类型查询图书，按 current_pos 升序排序，默认限制 100 条。

        供 list_rankings 端点使用。
        """
        result = await self.db.execute(
            select(FanqieBook)
            .where(FanqieBook.rank_type == rank_type)
            .order_by(FanqieBook.current_pos)
            .limit(limit)
        )
        return result.scalars().all()

    async def find_category_by_fanqie_id(self, fanqie_id: str) -> FanqieCategory | None:
        """按 fanqie_id 查询分类，不存在返回 None。

        供 category_books 端点确定 gender 使用。
        """
        result = await self.db.execute(
            select(FanqieCategory).where(FanqieCategory.fanqie_id == fanqie_id)
        )
        return result.scalar_one_or_none()

    async def list_books_by_category_and_pos_field(
        self,
        category_id: str,
        pos_field: str,
        limit: int,
    ) -> Sequence[FanqieBook]:
        """按分类和 pos 字段查询图书。

        只返回 pos 字段非空的记录，按 pos 升序排序，限制 limit 条。
        pos_field 取值：male_reading_pos / male_new_pos / female_reading_pos / female_new_pos。

        供 category_books 端点使用。
        """
        pos_attr = getattr(FanqieBook, pos_field)
        result = await self.db.execute(
            select(FanqieBook)
            .where(
                FanqieBook.category_id == category_id,
                pos_attr is not None,
            )
            .order_by(pos_attr)
            .limit(limit)
        )
        return result.scalars().all()
