"""Read-only coverage of an event relative to the report currently displayed."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.content_event_consumption_repo import (
    ContentEventConsumptionRepository,
    EventAssignment,
    EventDisplayGroup,
)
from app.repositories.content_event_repo import ContentEventRepository
from app.services.content_event_service import ContentEventConflictError, ContentEventNotFoundError


def coverage_payload(group: EventDisplayGroup, *, representative_id: int, member_offset: int = 0) -> dict:
    def timestamp(value):
        return value.isoformat() if isinstance(value, datetime) else value

    next_offset = member_offset + len(group.members)
    return {
        "event_id": group.event_group_id,
        "version": group.version,
        "canonical_id": group.canonical_content_id,
        "representative_id": representative_id,
        "member_count": group.member_count,
        "source_count": group.source_count,
        "update_count": group.update_count,
        "member_offset": member_offset,
        "next_offset": next_offset,
        "has_more": next_offset < group.member_count,
        "members": [
            {
                "id": member.content_id,
                "title": member.title,
                "url": member.url,
                "source_name": member.source_name,
                "source_type": member.source_type,
                "platform": member.platform,
                "published_at": timestamp(member.published_at),
                "crawled_at": timestamp(member.crawled_at),
                "relation_type": member.relation_type,
            }
            for member in group.members
        ],
    }


async def attach_event_coverage(
    db: AsyncSession,
    items: list[dict],
    *,
    visible_user_id: int | None,
    assignments: dict[int, EventAssignment] | None = None,
) -> None:
    repo = ContentEventConsumptionRepository(db)
    if assignments is None:
        assignments = await repo.resolve_today_pick_assignments(
            [int(item["id"]) for item in items], visible_user_id=visible_user_id
        )
    representatives = {
        assignment.event_group_id: int(item["id"])
        for item in items
        if (assignment := assignments.get(int(item["id"]))) is not None
    }
    groups = await repo.load_display_groups(
        representatives, visible_user_id=visible_user_id, member_limit=5, representatives=representatives
    )
    for item in items:
        assignment = assignments.get(int(item["id"]))
        if assignment is not None and (group := groups.get(assignment.event_group_id)) is not None:
            item["normalization"] = coverage_payload(group, representative_id=int(item["id"]))


async def get_event_coverage(
    db: AsyncSession,
    content_id: int,
    *,
    visible_user_id: int | None,
    member_offset: int,
    member_limit: int,
    expected_event_id: int | None = None,
    expected_version: int | None = None,
) -> dict | None:
    content = await ContentEventRepository(db).get_content(content_id)
    if content is None or (content.owner_user_id is not None and content.owner_user_id != visible_user_id):
        raise ContentEventNotFoundError("content not found")
    repo = ContentEventConsumptionRepository(db)
    assignments = await repo.resolve_today_pick_assignments([content_id], visible_user_id=visible_user_id)
    assignment = assignments.get(content_id)
    if assignment is None:
        if expected_event_id is not None or expected_version is not None:
            raise ContentEventConflictError("event membership changed; reload coverage")
        return None
    groups = await repo.load_display_groups(
        [assignment.event_group_id],
        visible_user_id=visible_user_id,
        member_offset=member_offset,
        member_limit=member_limit,
        representatives={assignment.event_group_id: content_id},
    )
    group = groups.get(assignment.event_group_id)
    # A change before the share lock was acquired must not append another
    # event/version to the caller's existing page.
    current = (await repo.resolve_today_pick_assignments([content_id], visible_user_id=visible_user_id)).get(content_id)
    if (
        group is None
        or current is None
        or current.event_group_id != assignment.event_group_id
        or (expected_event_id is not None and group.event_group_id != expected_event_id)
        or (expected_version is not None and group.version != expected_version)
    ):
        raise ContentEventConflictError("event changed; reload coverage")
    return coverage_payload(group, representative_id=content_id, member_offset=member_offset)
