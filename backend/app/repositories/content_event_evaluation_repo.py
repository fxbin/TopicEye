"""Read projections for a public, frozen event evaluation dataset."""

from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.models.content import ContentItem, ContentStatus
from app.models.content_event import ContentEventGroup, ContentEventMember, EventStatus


class ContentEventEvaluationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def projection_columns():
        return load_only(
            ContentItem.id,
            ContentItem.owner_user_id,
            ContentItem.title,
            ContentItem.summary,
            ContentItem.source_name,
            ContentItem.source_type,
            ContentItem.created_at,
            ContentItem.published_at,
            ContentItem.crawled_at,
        )

    async def public_canonicals(self, *, since: datetime, as_of: datetime, limit: int):
        return (
            await self.db.execute(
                select(ContentItem, ContentEventGroup.id, ContentEventGroup.version)
                .options(self.projection_columns())
                .join(ContentEventGroup, ContentEventGroup.canonical_content_id == ContentItem.id)
                .where(
                    ContentItem.owner_user_id.is_(None),
                    ContentEventGroup.owner_user_id.is_(None),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    ContentEventGroup.last_occurrence_at >= since,
                    ContentEventGroup.created_at <= as_of,
                    ContentItem.created_at <= as_of,
                )
                .order_by(ContentEventGroup.last_occurrence_at.desc(), ContentEventGroup.id.desc())
                .limit(limit)
            )
        ).all()

    async def public_incoming(self, *, since: datetime, as_of: datetime, limit: int):
        # Match the production scanner's unassigned definition, including
        # pending/rejected members: human decisions are not fresh candidates.
        return list(
            (
                await self.db.scalars(
                    select(ContentItem)
                    .options(self.projection_columns())
                    .where(
                        ContentItem.owner_user_id.is_(None),
                        ContentItem.status == ContentStatus.ANALYZED,
                        ContentItem.created_at >= since,
                        ContentItem.created_at <= as_of,
                        ~exists(
                            select(ContentEventGroup.id).where(ContentEventGroup.canonical_content_id == ContentItem.id)
                        ),
                        ~exists(select(ContentEventMember.id).where(ContentEventMember.content_id == ContentItem.id)),
                    )
                    .order_by(
                        ContentItem.published_at.asc().nulls_last(),
                        ContentItem.crawled_at.asc().nulls_last(),
                        ContentItem.created_at.asc(),
                        ContentItem.id.asc(),
                    )
                    .limit(limit)
                )
            ).all()
        )
