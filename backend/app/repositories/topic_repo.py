"""
Repository for TopicGroup model operations.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.topic import TopicGroup
from app.repositories.base import BaseRepository


class TopicRepository(BaseRepository[TopicGroup]):
    """TopicGroup table CRUD + get-or-create helper."""

    model = TopicGroup

    async def get_or_create(self, name: str, **defaults) -> TopicGroup:
        """Return an existing TopicGroup by name, or create one if missing."""
        stmt = select(TopicGroup).where(TopicGroup.name == name)
        result = await self.db.execute(stmt)
        topic = result.scalar_one_or_none()

        if topic is not None:
            return topic

        return await self.create(name=name, **defaults)

    async def list_ordered_by_best_score(self) -> Sequence[TopicGroup]:
        """返回所有 topic，按 best_score 倒序排列。"""
        stmt = select(TopicGroup).order_by(TopicGroup.best_score.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        """统计 topic 总数。"""
        result = await self.db.execute(select(func.count(TopicGroup.id)))
        return result.scalar() or 0
