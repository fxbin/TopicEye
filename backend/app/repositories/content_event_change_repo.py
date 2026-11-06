"""Small fresh column projections for read-only event change comparisons."""

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_event import ContentEventGroup, ContentEventMember, EventReviewStatus, EventStatus


class ContentEventChangeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _visible(column, user_id):
        return column.is_(None) if user_id is None else or_(column.is_(None), column == user_id)

    async def visible_content(self, content_id: int, user_id: int) -> bool:
        return (
            await self.db.scalar(
                select(ContentItem.id).where(
                    ContentItem.id == content_id, self._visible(ContentItem.owner_user_id, user_id)
                )
            )
        ) is not None

    async def group_state(self, content_id: int, user_id: int) -> dict | None:
        membership = select(ContentEventMember.event_group_id).where(
            ContentEventMember.content_id == content_id,
            ContentEventMember.review_status.in_([EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED]),
        )
        stmt = (
            select(
                ContentEventGroup.id.label("event_id"),
                ContentEventGroup.version,
                ContentEventGroup.canonical_content_id.label("canonical_id"),
            )
            .where(
                ContentEventGroup.status == EventStatus.ACTIVE,
                self._visible(ContentEventGroup.owner_user_id, user_id),
                or_(ContentEventGroup.canonical_content_id == content_id, ContentEventGroup.id.in_(membership)),
            )
            .limit(1)
        )
        row = (await self.db.execute(stmt)).mappings().first()
        return dict(row) if row else None

    async def materials(self, group: dict, ids: list[int], user_id: int) -> list[dict]:
        accepted = select(ContentEventMember.content_id).where(
            ContentEventMember.event_group_id == group["event_id"],
            ContentEventMember.review_status.in_([EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED]),
        )
        stmt = select(
            ContentItem.id,
            ContentItem.title,
            ContentItem.url,
            ContentItem.source_name,
            ContentItem.published_at,
            ContentItem.summary,
            ContentItem.raw_content,
        ).where(
            ContentItem.id.in_(ids),
            self._visible(ContentItem.owner_user_id, user_id),
            or_(ContentItem.id == group["canonical_id"], ContentItem.id.in_(accepted)),
        )
        return [dict(row) for row in (await self.db.execute(stmt)).mappings().all()]
