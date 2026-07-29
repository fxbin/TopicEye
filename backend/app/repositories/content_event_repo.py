"""Persistence boundary for canonical content events.

The repository intentionally owns both event-group and event-member ORM
access.  Keeping them behind one boundary avoids repository-to-repository
dependencies and lets callers load a complete event without per-member
queries.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)


@dataclass(frozen=True)
class EventMemberRow:
    """A member and its content loaded by one joined query."""

    member: ContentEventMember
    content: ContentItem


@dataclass(frozen=True)
class EventBundle:
    """The complete read model needed by the event domain service."""

    group: ContentEventGroup
    canonical: ContentItem
    members: Sequence[EventMemberRow]
    member_count: int
    source_count: int


@dataclass(frozen=True)
class EventReviewRow:
    """A review candidate with the group and content needed by admin UI."""

    member: ContentEventMember
    group: ContentEventGroup
    content: ContentItem


class ContentEventRepository:
    """ORM access for event groups, members, and the legacy projection."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _visible_owner_clause(visible_user_id: int | None):
        if visible_user_id is None:
            return ContentEventGroup.owner_user_id.is_(None)
        return or_(
            ContentEventGroup.owner_user_id.is_(None),
            ContentEventGroup.owner_user_id == visible_user_id,
        )

    async def get_content(
        self,
        content_id: int,
        *,
        for_update: bool = False,
    ) -> ContentItem | None:
        stmt = select(ContentItem).where(ContentItem.id == content_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_contents(
        self,
        content_ids: Iterable[int],
        *,
        for_update: bool = False,
    ) -> list[ContentItem]:
        ids = sorted(set(content_ids))
        if not ids:
            return []
        stmt = select(ContentItem).where(ContentItem.id.in_(ids)).order_by(ContentItem.id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_group(
        self,
        event_id: int,
        *,
        for_update: bool = False,
    ) -> ContentEventGroup | None:
        stmt = select(ContentEventGroup).where(ContentEventGroup.id == event_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_group_for_content(
        self,
        content_id: int,
        *,
        for_update: bool = False,
    ) -> ContentEventGroup | None:
        """Resolve a canonical or member content id to its single event."""

        member_event = select(ContentEventMember.event_group_id).where(ContentEventMember.content_id == content_id)
        stmt = select(ContentEventGroup).where(
            or_(
                ContentEventGroup.canonical_content_id == content_id,
                ContentEventGroup.id.in_(member_event),
            )
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def resolve_visible_group(
        self,
        content_id: int,
        *,
        visible_user_id: int | None,
        include_shadow: bool = False,
    ) -> ContentEventGroup | None:
        member_event = select(ContentEventMember.event_group_id).where(ContentEventMember.content_id == content_id)
        statuses = [EventStatus.ACTIVE]
        if include_shadow:
            statuses.append(EventStatus.SHADOW)
        else:
            member_event = member_event.where(
                ContentEventMember.review_status.in_([EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED])
            )
        stmt = (
            select(ContentEventGroup)
            .where(
                or_(
                    ContentEventGroup.canonical_content_id == content_id,
                    ContentEventGroup.id.in_(member_event),
                ),
                ContentEventGroup.status.in_(statuses),
                self._visible_owner_clause(visible_user_id),
            )
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_member(
        self,
        content_id: int,
        *,
        for_update: bool = False,
    ) -> ContentEventMember | None:
        stmt = select(ContentEventMember).where(ContentEventMember.content_id == content_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_member_by_id(
        self,
        member_id: int,
        *,
        for_update: bool = False,
    ) -> ContentEventMember | None:
        stmt = select(ContentEventMember).where(ContentEventMember.id == member_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_member_rows(
        self,
        event_id: int,
        *,
        include_unaccepted: bool = True,
        offset: int = 0,
        limit: int | None = None,
        for_update: bool = False,
    ) -> list[EventMemberRow]:
        stmt = (
            select(ContentEventMember, ContentItem)
            .join(ContentItem, ContentItem.id == ContentEventMember.content_id)
            .where(ContentEventMember.event_group_id == event_id)
        )
        if not include_unaccepted:
            stmt = stmt.where(
                ContentEventMember.review_status.in_([EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED])
            )
        stmt = stmt.order_by(
            ContentItem.published_at.asc().nulls_last(),
            ContentItem.crawled_at.asc().nulls_last(),
            ContentItem.created_at.asc(),
            ContentItem.id.asc(),
        ).offset(max(0, offset))
        if limit is not None:
            stmt = stmt.limit(max(0, limit))
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return [EventMemberRow(member=row[0], content=row[1]) for row in result.all()]

    async def get_event_bundle(
        self,
        group: ContentEventGroup,
        *,
        member_offset: int = 0,
        member_limit: int = 20,
        include_unaccepted: bool = False,
    ) -> EventBundle | None:
        """Load one event with database pagination and fixed query count."""

        accepted_clause = ContentEventMember.review_status.in_([EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED])
        owner_clause = (
            ContentItem.owner_user_id.is_(None)
            if group.owner_user_id is None
            else ContentItem.owner_user_id == group.owner_user_id
        )
        canonical_result = await self.db.execute(
            select(ContentItem).where(
                ContentItem.id == group.canonical_content_id,
                owner_clause,
            )
        )
        canonical = canonical_result.scalar_one_or_none()
        if canonical is None:
            return None

        source_stmt = (
            select(
                ContentItem.source_id,
                ContentItem.source_name,
                func.count(ContentEventMember.id),
            )
            .join(
                ContentEventMember,
                ContentEventMember.content_id == ContentItem.id,
            )
            .where(
                ContentEventMember.event_group_id == group.id,
                owner_clause,
            )
            .group_by(ContentItem.source_id, ContentItem.source_name)
        )
        if not include_unaccepted:
            source_stmt = source_stmt.where(accepted_clause)
        source_result = await self.db.execute(source_stmt)
        source_rows = source_result.all()
        member_count = sum(int(row[2]) for row in source_rows)
        source_keys = {(row[0], row[1]) for row in source_rows}
        source_keys.add((canonical.source_id, canonical.source_name))

        member_stmt = (
            select(ContentEventMember, ContentItem)
            .join(ContentItem, ContentItem.id == ContentEventMember.content_id)
            .where(
                ContentEventMember.event_group_id == group.id,
                owner_clause,
            )
        )
        if not include_unaccepted:
            member_stmt = member_stmt.where(accepted_clause)
        member_stmt = (
            member_stmt.order_by(
                ContentItem.published_at.asc().nulls_last(),
                ContentItem.crawled_at.asc().nulls_last(),
                ContentItem.created_at.asc(),
                ContentItem.id.asc(),
            )
            .offset(max(0, member_offset))
            .limit(max(0, member_limit))
        )
        member_result = await self.db.execute(member_stmt)
        member_rows = [EventMemberRow(member=row[0], content=row[1]) for row in member_result.all()]
        return EventBundle(
            group=group,
            canonical=canonical,
            members=member_rows,
            member_count=member_count,
            source_count=len(source_keys),
        )

    async def list_reviews(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        review_status: str | None = None,
    ) -> tuple[list[EventReviewRow], int]:
        filters = []
        if review_status is not None:
            filters.append(ContentEventMember.review_status == review_status)
        count_stmt = select(func.count()).select_from(ContentEventMember).where(*filters)
        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar_one())
        stmt = (
            select(ContentEventMember, ContentEventGroup, ContentItem)
            .join(
                ContentEventGroup,
                ContentEventGroup.id == ContentEventMember.event_group_id,
            )
            .join(ContentItem, ContentItem.id == ContentEventMember.content_id)
            .where(*filters)
            .order_by(
                ContentEventMember.matched_at.desc(),
                ContentEventMember.id.desc(),
            )
            .offset((max(1, page) - 1) * max(1, page_size))
            .limit(max(1, page_size))
        )
        result = await self.db.execute(stmt)
        return (
            [EventReviewRow(member=row[0], group=row[1], content=row[2]) for row in result.all()],
            total,
        )

    async def list_all_legacy_links(self) -> list[ContentItem]:
        result = await self.db.execute(
            select(ContentItem).where(ContentItem.duplicate_of.is_not(None)).order_by(ContentItem.id)
        )
        return list(result.scalars().all())

    async def create_group(self, **values) -> ContentEventGroup:
        group = ContentEventGroup(**values)
        self.db.add(group)
        await self.db.flush()
        return group

    async def create_member(self, **values) -> ContentEventMember:
        member = ContentEventMember(**values)
        self.db.add(member)
        await self.db.flush()
        return member

    async def delete_member(self, member: ContentEventMember) -> None:
        await self.db.delete(member)
        await self.db.flush()

    async def sync_duplicate_projection(self, event_id: int) -> None:
        """Flatten the compatibility projection for one event.

        Canonicals and non-duplicate relations always project to ``NULL``.
        Rejected members are also detached from the legacy projection.
        """

        group = await self.get_group(event_id)
        if group is None:
            return
        if group.status == EventStatus.SHADOW:
            return
        member_rows = await self.list_member_rows(
            event_id,
            include_unaccepted=True,
        )
        canonical = await self.get_content(group.canonical_content_id)
        if canonical is not None:
            canonical.duplicate_of = None
            canonical.similarity_score = None
        for row in member_rows:
            row.content.duplicate_of = None
            row.content.similarity_score = None
            if (
                group.status == EventStatus.ACTIVE
                and row.member.relation_type == "duplicate"
                and row.member.review_status in {EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED}
            ):
                row.content.duplicate_of = group.canonical_content_id
                row.content.similarity_score = row.member.confidence
        await self.db.flush()

    async def assigned_content_ids(self, content_ids: Iterable[int]) -> set[int]:
        """Return assigned IDs with two queries regardless of batch size."""

        ids = sorted(set(content_ids))
        if not ids:
            return set()
        canonical_result = await self.db.execute(
            select(ContentEventGroup.canonical_content_id).where(ContentEventGroup.canonical_content_id.in_(ids))
        )
        member_result = await self.db.execute(
            select(ContentEventMember.content_id).where(ContentEventMember.content_id.in_(ids))
        )
        return {
            *(int(value) for value in canonical_result.scalars().all()),
            *(int(value) for value in member_result.scalars().all()),
        }
