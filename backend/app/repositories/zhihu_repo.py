"""
Repository for Zhihu model operations.

封装知乎盐选专栏的查询逻辑：
- 专辑列表（支持 sort_type/category/subcategory 过滤，含 fallback 查询）
- 专辑计数（与列表过滤条件一致）
- 分类列表（按 parent_id 查询，支持一级/二级分类）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.sql import Select

from app.models.zhihu import ZhihuAlbum, ZhihuCategory
from app.repositories.base import BaseRepository


class ZhihuRepository(BaseRepository[ZhihuAlbum]):
    """知乎盐选专栏 CRUD + 分类/专辑查询。"""

    model = ZhihuAlbum

    @staticmethod
    def _apply_album_filters(
        query: Select,
        sort_type: str,
        category: str | None,
        subcategories: tuple[str, ...],
    ) -> Select:
        """应用 sort_type/category/subcategories 过滤条件到 query。

        - sort_type：必填，精确匹配
        - category：可选，一级分类名精确匹配
        - subcategories：可选，二级分类名；单个用 ==，多个用 IN
        """
        query = query.where(ZhihuAlbum.sort_type == sort_type)
        if category:
            query = query.where(ZhihuAlbum.category1_name == category)
        if len(subcategories) == 1:
            query = query.where(ZhihuAlbum.category2_name == subcategories[0])
        elif subcategories:
            query = query.where(ZhihuAlbum.category2_name.in_(subcategories))
        return query

    async def list_albums_with_filters(
        self,
        *,
        sort_type: str,
        category: str | None = None,
        subcategories: tuple[str, ...] = (),
        limit: int = 20,
        offset: int = 0,
    ) -> Sequence[ZhihuAlbum]:
        """按 sort_type/category/subcategories 查询专辑列表。

        排序：position ASC, updated_at DESC。
        供 list_albums 端点使用（含 fallback 查询场景）。
        """
        query = self._apply_album_filters(select(ZhihuAlbum), sort_type, category, subcategories)
        query = (
            query.order_by(ZhihuAlbum.position.asc(), ZhihuAlbum.updated_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(query)
        return result.scalars().all()

    async def count_albums_with_filters(
        self,
        *,
        sort_type: str,
        category: str | None = None,
        subcategories: tuple[str, ...] = (),
    ) -> int:
        """按 sort_type/category/subcategories 统计专辑数量。

        与 list_albums_with_filters 使用相同的过滤条件。
        """
        count_q = self._apply_album_filters(
            select(func.count()).select_from(ZhihuAlbum),
            sort_type,
            category,
            subcategories,
        )
        result = await self.db.execute(count_q)
        return int(result.scalar() or 0)

    async def list_categories_by_parent_id(self, parent_id: str | None) -> Sequence[ZhihuCategory]:
        """按 parent_id 查询分类列表，按 sort 升序排序。

        parent_id=None 表示查询一级分类（parent_id IS NULL）。
        供 list_categories 端点使用。
        """
        if parent_id:
            query = (
                select(ZhihuCategory)
                .where(ZhihuCategory.parent_id == parent_id)
                .order_by(ZhihuCategory.sort)
            )
        else:
            query = (
                select(ZhihuCategory)
                .where(ZhihuCategory.parent_id is None)
                .order_by(ZhihuCategory.sort)
            )
        result = await self.db.execute(query)
        return result.scalars().all()
