from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ignored import IgnoredItem


class IgnoredRepo:
    """忽略记录的唯一 ORM 入口。

    两种口径：
    - ``user_id=None`` 写入/删除的是**管理员全局屏蔽**（对所有用户生效）；
    - ``user_id=<uid>`` 写入/删除的是**用户个人「不感兴趣」**（仅该用户生效）。
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ignore(
        self,
        content_id: int,
        reason: str = "not_interested",
        *,
        user_id: int | None = None,
    ) -> IgnoredItem:
        existing = await self.get_by_content_id(content_id, user_id=user_id)
        if existing:
            return existing
        obj = IgnoredItem(content_id=content_id, reason=reason, user_id=user_id)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def unignore(self, content_id: int, *, user_id: int | None = None) -> bool:
        stmt = delete(IgnoredItem).where(
            IgnoredItem.content_id == content_id,
            IgnoredItem.user_id.is_(None) if user_id is None else IgnoredItem.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0

    async def get_by_content_id(self, content_id: int, *, user_id: int | None = None) -> IgnoredItem | None:
        stmt = select(IgnoredItem).where(
            IgnoredItem.content_id == content_id,
            IgnoredItem.user_id.is_(None) if user_id is None else IgnoredItem.user_id == user_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_ignored_ids(self, *, user_id: int | None = None) -> set[int]:
        """对 ``user_id`` 生效的排除集：全局屏蔽 + 该用户个人忽略。

        ``user_id=None``（匿名访问）只排除全局屏蔽，不受任何个人忽略影响。
        """
        stmt = select(IgnoredItem.content_id)
        if user_id is None:
            stmt = stmt.where(IgnoredItem.user_id.is_(None))
        else:
            stmt = stmt.where((IgnoredItem.user_id.is_(None)) | (IgnoredItem.user_id == user_id))
        result = await self.db.execute(stmt)
        return {row[0] for row in result.all()}

    async def list_personal_ignored_ids(self, user_id: int) -> set[int]:
        """仅该用户的个人忽略（不含全局屏蔽）。"""
        stmt = select(IgnoredItem.content_id).where(IgnoredItem.user_id == user_id)
        result = await self.db.execute(stmt)
        return {row[0] for row in result.all()}

    async def list_ignored(self, page: int = 1, page_size: int = 20) -> tuple[Sequence[IgnoredItem], int]:
        from sqlalchemy import func

        count_result = await self.db.execute(select(func.count()).select_from(IgnoredItem))
        total = count_result.scalar() or 0
        result = await self.db.execute(
            select(IgnoredItem).order_by(IgnoredItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return result.scalars().all(), total
