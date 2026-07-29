from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401 - register all FK targets in Base.metadata
from app.core.database import Base
from app.models.content import ContentItem
from app.models.content_event import (
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventNotFoundError,
    ContentEventService,
    ContentEventValidationError,
    EventMemberInput,
)


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(
            text(
                """
                CREATE TRIGGER trg_test_event_member_not_canonical_insert
                BEFORE INSERT ON content_event_members
                FOR EACH ROW
                WHEN EXISTS (
                    SELECT 1 FROM content_event_groups
                    WHERE id = NEW.event_group_id
                      AND canonical_content_id = NEW.content_id
                )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'canonical content cannot also be an event member'
                    );
                END
                """
            )
        )
        await conn.execute(
            text(
                """
                CREATE TRIGGER trg_test_event_canonical_not_member_update
                BEFORE UPDATE OF canonical_content_id ON content_event_groups
                FOR EACH ROW
                WHEN EXISTS (
                    SELECT 1 FROM content_event_members
                    WHERE event_group_id = NEW.id
                      AND content_id = NEW.canonical_content_id
                )
                BEGIN
                    SELECT RAISE(
                        ABORT,
                        'event member cannot become canonical before member removal'
                    );
                END
                """
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db:
        yield db
        await db.rollback()
    await engine.dispose()


async def _content(
    db,
    title: str,
    *,
    hours: int,
    owner_user_id: int | None = None,
    source_name: str | None = None,
) -> ContentItem:
    moment = datetime(2026, 7, 29, tzinfo=UTC) + timedelta(hours=hours)
    item = ContentItem(
        title=title,
        url=f"https://example.com/{title}",
        owner_user_id=owner_user_id,
        source_name=source_name or title,
        source_type="rss",
        published_at=moment,
        crawled_at=moment + timedelta(minutes=1),
        created_at=moment + timedelta(minutes=2),
    )
    db.add(item)
    await db.flush()
    return item


async def _members(db, event_id: int) -> list[ContentEventMember]:
    result = await db.execute(
        select(ContentEventMember)
        .where(ContentEventMember.event_group_id == event_id)
        .order_by(ContentEventMember.content_id)
    )
    return list(result.scalars().all())


@pytest.mark.asyncio
async def test_earliest_canonical_manual_lock_and_unlock(session):
    later = await _content(session, "later", hours=3)
    earlier = await _content(session, "earlier", hours=1)
    service = ContentEventService(session)

    group = await service.create_event(
        [later.id, earlier.id],
        owner_user_id=None,
    )
    assert group.canonical_content_id == earlier.id
    assert group.version == 1
    assert [member.content_id for member in await _members(session, group.id)] == [
        later.id
    ]

    group = await service.set_canonical(
        group.id,
        later.id,
        reason="editorial lead",
        expected_version=1,
        actor_user_id=None,
    )
    assert group.canonical_content_id == later.id
    assert group.canonical_locked is True
    assert group.version == 2
    assert [member.content_id for member in await _members(session, group.id)] == [
        earlier.id
    ]

    oldest = await _content(session, "oldest", hours=0)
    group = await service.add_member(
        group.id,
        oldest.id,
        confidence=0.99,
    )
    assert group.canonical_content_id == later.id
    assert group.version == 3

    group = await service.unlock_canonical(
        group.id,
        reason="return to policy",
        expected_version=3,
    )
    assert group.canonical_content_id == oldest.id
    assert group.canonical_locked is False
    assert group.version == 4
    assert {
        member.content_id for member in await _members(session, group.id)
    } == {earlier.id, later.id}


@pytest.mark.asyncio
async def test_relation_truth_and_low_confidence_pending(session):
    canonical = await _content(session, "canonical", hours=0)
    duplicate = await _content(session, "duplicate", hours=1)
    corroboration = await _content(session, "corroboration", hours=2)
    update = await _content(session, "update", hours=3)
    uncertain = await _content(session, "uncertain", hours=4)
    service = ContentEventService(session)

    group = await service.create_event(
        [
            canonical.id,
            duplicate.id,
            corroboration.id,
            update.id,
            uncertain.id,
        ],
        owner_user_id=None,
        members={
            duplicate.id: EventMemberInput(
                content_id=duplicate.id,
                relation_type="duplicate",
                confidence=0.99,
            ),
            corroboration.id: EventMemberInput(
                content_id=corroboration.id,
                relation_type="corroboration",
                confidence=0.95,
            ),
            update.id: EventMemberInput(
                content_id=update.id,
                relation_type="update",
                confidence=0.9,
            ),
            uncertain.id: EventMemberInput(
                content_id=uncertain.id,
                relation_type="duplicate",
                confidence=0.4,
            ),
        },
    )

    member_by_content = {member.content_id: member for member in await _members(session, group.id)}
    assert member_by_content[duplicate.id].review_status == EventReviewStatus.AUTO
    assert member_by_content[duplicate.id].confidence == pytest.approx(0.99)
    assert member_by_content[corroboration.id].relation_type == "corroboration"
    assert member_by_content[update.id].relation_type == "update"
    assert member_by_content[uncertain.id].review_status == EventReviewStatus.PENDING
    assert await service.get_event_detail(uncertain.id, visible_user_id=None) is None


@pytest.mark.asyncio
async def test_create_event_never_promotes_pending_candidate_to_canonical(
    session,
):
    pending_earlier = await _content(session, "pending-earlier", hours=0)
    accepted_seed = await _content(session, "accepted-seed", hours=2)
    service = ContentEventService(session)

    group = await service.create_event(
        [pending_earlier.id, accepted_seed.id],
        owner_user_id=None,
        members={
            pending_earlier.id: EventMemberInput(
                content_id=pending_earlier.id,
                confidence=0.4,
            )
        },
    )
    assert group.canonical_content_id == accepted_seed.id
    member = (await _members(session, group.id))[0]
    assert member.content_id == pending_earlier.id
    assert member.review_status == EventReviewStatus.PENDING
    assert (
        await service.get_event_detail(
            pending_earlier.id,
            visible_user_id=None,
        )
        is None
    )


@pytest.mark.asyncio
async def test_create_event_rejects_pending_explicit_canonical_and_all_pending(
    session,
):
    pending = await _content(session, "pending", hours=0)
    accepted = await _content(session, "accepted", hours=1)
    service = ContentEventService(session)
    with pytest.raises(
        ContentEventValidationError,
        match="canonical content must be an accepted candidate",
    ):
        await service.create_event(
            [pending.id, accepted.id],
            owner_user_id=None,
            members={
                pending.id: EventMemberInput(
                    content_id=pending.id,
                    confidence=0.2,
                )
            },
            canonical_content_id=pending.id,
            canonical_locked=True,
        )

    pending_a = await _content(session, "pending-a", hours=2)
    pending_b = await _content(session, "pending-b", hours=3)
    with pytest.raises(
        ContentEventValidationError,
        match="at least one accepted canonical candidate",
    ):
        await service.create_event(
            [pending_a.id, pending_b.id],
            owner_user_id=None,
            members={
                pending_a.id: EventMemberInput(
                    content_id=pending_a.id,
                    confidence=0.2,
                ),
                pending_b.id: EventMemberInput(
                    content_id=pending_b.id,
                    confidence=0.3,
                ),
            },
        )

    single = await _content(session, "single-seed", hours=4)
    single_group = await service.create_event(
        [single.id],
        owner_user_id=None,
    )
    assert single_group.canonical_content_id == single.id


@pytest.mark.asyncio
async def test_scope_single_membership_and_self_guards(session):
    public_a = await _content(session, "public-a", hours=0)
    public_b = await _content(session, "public-b", hours=1)
    private = await _content(session, "private", hours=2, owner_user_id=7)
    service = ContentEventService(session)

    with pytest.raises(ContentEventValidationError, match="same owner"):
        await service.create_event(
            [public_a.id, private.id],
            owner_user_id=None,
        )

    group = await service.create_event(
        [public_a.id, public_b.id],
        owner_user_id=None,
    )
    with pytest.raises(ContentEventConflictError, match="already belong"):
        await service.create_event([public_b.id], owner_user_id=None)
    with pytest.raises(ContentEventValidationError, match="cannot also"):
        await service.add_member(group.id, group.canonical_content_id)
    with pytest.raises(ContentEventValidationError, match="same owner"):
        await service.add_member(group.id, private.id)


@pytest.mark.asyncio
async def test_move_member_recomputes_both_groups_and_reselects_canonical(
    session,
):
    source_canonical = await _content(session, "source-canonical", hours=0)
    moving = await _content(session, "moving", hours=2)
    target_canonical = await _content(session, "target-canonical", hours=4)
    target_child = await _content(session, "target-child", hours=5)
    service = ContentEventService(session)
    source = await service.create_event(
        [source_canonical.id, moving.id],
        owner_user_id=None,
    )
    target = await service.create_event(
        [target_canonical.id, target_child.id],
        owner_user_id=None,
    )

    target = await service.move_member(
        moving.id,
        target.id,
        confidence=0.99,
    )
    assert source.version == 2
    assert target.version == 2
    assert target.canonical_content_id == moving.id
    assert await _members(session, source.id) == []
    assert [member.content_id for member in await _members(session, target.id)] == [
        target_canonical.id,
        target_child.id,
    ]


@pytest.mark.asyncio
async def test_review_uses_occ_and_rejected_relation_is_not_served(session):
    canonical = await _content(session, "canonical", hours=0)
    member_content = await _content(session, "member", hours=1)
    service = ContentEventService(session)
    group = await service.create_event(
        [canonical.id, member_content.id],
        owner_user_id=None,
    )
    member = (await _members(session, group.id))[0]

    with pytest.raises(ContentEventConflictError, match="version conflict"):
        await service.review_relation(
            member.id,
            decision="reject",
            relation_type=None,
            reason="not the same event",
            expected_version=99,
        )

    group = await service.review_relation(
        member.id,
        decision="reject",
        relation_type=None,
        reason="not the same event",
        expected_version=1,
    )
    assert group.version == 2
    await session.refresh(member)
    assert member.review_status == EventReviewStatus.REJECTED
    detail = await service.get_event_detail(
        canonical.id,
        visible_user_id=None,
    )
    assert detail is not None
    assert detail["member_count"] == 0


@pytest.mark.asyncio
async def test_pending_member_cannot_be_manual_canonical_and_accept_reselects_earliest(
    session,
):
    canonical = await _content(session, "canonical", hours=2)
    pending_content = await _content(session, "pending-earlier", hours=0)
    service = ContentEventService(session)
    group = await service.create_event([canonical.id], owner_user_id=None)
    group = await service.add_member(
        group.id,
        pending_content.id,
        confidence=0.4,
    )
    assert group.canonical_content_id == canonical.id
    member = (await _members(session, group.id))[0]
    assert member.review_status == EventReviewStatus.PENDING

    with pytest.raises(ContentEventValidationError, match="accepted member"):
        await service.set_canonical(
            group.id,
            pending_content.id,
            reason="not reviewed yet",
            expected_version=2,
        )

    group = await service.review_relation(
        member.id,
        decision="accept",
        relation_type="duplicate",
        reason="reviewed as the same event",
        expected_version=2,
    )
    assert group.version == 3
    assert group.canonical_content_id == pending_content.id
    assert [member.content_id for member in await _members(session, group.id)] == [
        canonical.id
    ]


@pytest.mark.asyncio
async def test_shadow_and_archived_events_are_not_served(session):
    canonical = await _content(session, "canonical", hours=0)
    shadow_child = await _content(session, "shadow-child", hours=1)
    service = ContentEventService(session)
    shadow = await service.create_event(
        [canonical.id, shadow_child.id],
        owner_user_id=None,
        status=EventStatus.SHADOW,
    )
    assert (
        await service.get_event_detail(shadow_child.id, visible_user_id=None)
        is None
    )

    shadow.status = EventStatus.ACTIVE
    await session.flush()
    assert (
        await service.get_event_detail(shadow_child.id, visible_user_id=None)
        is not None
    )

    shadow.status = EventStatus.ARCHIVED
    await session.flush()
    assert (
        await service.get_event_detail(shadow_child.id, visible_user_id=None)
        is None
    )


@pytest.mark.asyncio
async def test_detail_resolves_member_and_hides_shadow(session):
    canonical = await _content(
        session,
        "canonical",
        hours=0,
        source_name="source-a",
    )
    child = await _content(
        session,
        "child",
        hours=1,
        source_name="source-b",
    )
    service = ContentEventService(session)
    group = await service.create_event(
        [canonical.id, child.id],
        owner_user_id=None,
    )

    canonical_detail = await service.get_event_detail(
        canonical.id,
        visible_user_id=None,
    )
    child_detail = await service.get_event_detail(
        child.id,
        visible_user_id=None,
    )
    assert canonical_detail == child_detail
    assert canonical_detail is not None
    assert canonical_detail["canonical_id"] == canonical.id
    assert canonical_detail["member_count"] == 1
    assert canonical_detail["source_count"] == 2
    assert canonical_detail["members"][0]["id"] != child.id
    assert canonical_detail["members"][0]["content_id"] == child.id

    group.status = EventStatus.SHADOW
    await session.flush()
    assert await service.get_event_detail(child.id, visible_user_id=None) is None
    admin_detail = await service.get_event_detail(
        child.id,
        visible_user_id=None,
        include_shadow=True,
    )
    assert admin_detail is not None


@pytest.mark.asyncio
async def test_detail_paginates_members_but_counts_the_full_visible_event(
    session,
):
    contents = [
        await _content(
            session,
            f"content-{index}",
            hours=index,
            source_name=f"source-{index}",
        )
        for index in range(4)
    ]
    service = ContentEventService(session)
    await service.create_event(
        [content.id for content in contents],
        owner_user_id=None,
    )

    page = await service.get_event_detail(
        contents[0].id,
        visible_user_id=None,
        member_limit=1,
        member_offset=1,
    )
    assert page is not None
    assert page["member_count"] == 3
    assert page["source_count"] == 4
    assert page["has_more"] is True
    assert [member["content_id"] for member in page["members"]] == [contents[2].id]

    last_page = await service.get_event_detail(
        contents[0].id,
        visible_user_id=None,
        member_limit=1,
        member_offset=2,
    )
    assert last_page is not None
    assert last_page["has_more"] is False
    assert [member["content_id"] for member in last_page["members"]] == [contents[3].id]


@pytest.mark.asyncio
async def test_detail_enforces_exact_private_owner_scope(session):
    canonical = await _content(
        session,
        "private-canonical",
        hours=0,
        owner_user_id=7,
    )
    child = await _content(
        session,
        "private-child",
        hours=1,
        owner_user_id=7,
    )
    service = ContentEventService(session)
    await service.create_event(
        [canonical.id, child.id],
        owner_user_id=7,
    )

    with pytest.raises(ContentEventNotFoundError):
        await service.get_event_detail(child.id, visible_user_id=None)
    with pytest.raises(ContentEventNotFoundError):
        await service.get_event_detail(child.id, visible_user_id=8)
    detail = await service.get_event_detail(child.id, visible_user_id=7)
    assert detail is not None
    assert detail["owner_user_id"] == 7
