from __future__ import annotations
from typing import Optional, Sequence
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.ignored import IgnoredItem


class IgnoredRepo:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ignore(self, content_id: int, reason: str = "not_interested") -> IgnoredItem:
        existing = await self.get_by_content_id(content_id)
        if existing:
            return existing
        obj = IgnoredItem(content_id=content_id, reason=reason)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def unignore(self, content_id: int) -> bool:
        stmt = delete(IgnoredItem).where(IgnoredItem.content_id == content_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0

    async def get_by_content_id(self, content_id: int) -> Optional[IgnoredItem]:
        result = await self.db.execute(select(IgnoredItem).where(IgnoredItem.content_id == content_id))
        return result.scalar_one_or_none()

    async def list_ignored_ids(self) -> set[int]:
        result = await self.db.execute(select(IgnoredItem.content_id))
        return {row[0] for row in result.all()}

    async def list_ignored(self, page: int = 1, page_size: int = 20) -> tuple[Sequence[IgnoredItem], int]:
        from sqlalchemy import func

        count_result = await self.db.execute(select(func.count()).select_from(IgnoredItem))
        total = count_result.scalar() or 0
        result = await self.db.execute(
            select(IgnoredItem).order_by(IgnoredItem.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        )
        return result.scalars().all(), total
