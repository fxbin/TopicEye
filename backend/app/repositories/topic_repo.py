"""
Repository for TopicGroup model operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import func, select, update

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source
from app.models.topic import TopicGroup
from app.repositories._query_helpers import public_topic_clause
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.base import BaseRepository


class TopicRepository(BaseRepository[TopicGroup]):
    """TopicGroup table CRUD + get-or-create helper."""

    model = TopicGroup

    async def list_unassigned_candidates(self, cutoff: datetime, *, after_id: int, limit: int):
        latest_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
        stmt = (
            select(ContentItem, AiAnalysis, Source.weight.label("source_weight_db"))
            .select_from(ContentItem)
            .join(AiAnalysis, AiAnalysis.id == latest_id)
            .outerjoin(Source, Source.id == ContentItem.source_id)
            .where(
                ContentItem.status == ContentStatus.ANALYZED,
                ContentItem.topic_id.is_(None),
                ContentItem.owner_user_id.is_(None),
                ContentItem.created_at >= cutoff,
                ContentItem.id > after_id,
            )
            .order_by(ContentItem.id)
            .limit(limit)
        )
        return (await self.db.execute(stmt)).all()

    async def assign_public_items(self, topic_id: int, item_ids: list[int]) -> None:
        await self.db.execute(
            update(ContentItem)
            .where(ContentItem.id.in_(item_ids), ContentItem.owner_user_id.is_(None), ContentItem.topic_id.is_(None))
            .values(topic_id=topic_id)
        )

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

    async def list_public(self) -> Sequence[TopicGroup]:
        stmt = select(TopicGroup).where(public_topic_clause(TopicGroup.id, ContentItem))
        return (await self.db.execute(stmt.order_by(TopicGroup.best_score.desc()))).scalars().all()

    async def get_public(self, topic_id: int) -> TopicGroup | None:
        stmt = select(TopicGroup).where(TopicGroup.id == topic_id, public_topic_clause(TopicGroup.id, ContentItem))
        return (await self.db.execute(stmt)).scalar_one_or_none()
