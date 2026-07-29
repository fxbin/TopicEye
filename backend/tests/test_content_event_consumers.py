from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventRelationType,
    EventReviewStatus,
    EventStatus,
)
from app.models.content_evidence import ContentEvidenceLink, ContentEvidenceMark
from app.repositories.content_event_consumption_repo import (
    ContentEventConsumptionRepository,
    EventAssignment,
    EventDisplayGroup,
    EventDisplayMember,
    EvidenceContent,
    EvidenceEvent,
)
from app.services import evidence_service, today_picks
from app.services.evidence_service import discover_cross_source_evidence


def _content(
    title: str,
    *,
    owner_user_id: int | None = None,
    source_name: str,
    when: datetime,
) -> ContentItem:
    return ContentItem(
        title=title,
        url=f"https://example.com/{title}",
        source_name=source_name,
        source_type="RSS",
        owner_user_id=owner_user_id,
        crawled_at=when,
        published_at=when,
        status=ContentStatus.ANALYZED,
        created_at=when,
        updated_at=when,
    )


async def _seed_events(db):
    now = datetime.now(UTC)
    public_contents = [
        _content(
            "public-canonical",
            source_name="Publisher A",
            when=now - timedelta(hours=5),
        ),
        _content(
            "public-duplicate",
            source_name="Publisher A",
            when=now - timedelta(hours=4),
        ),
        _content(
            "public-corroboration",
            source_name="Publisher B",
            when=now - timedelta(hours=3),
        ),
        _content(
            "public-update",
            source_name="Publisher C",
            when=now - timedelta(hours=2),
        ),
        _content(
            "public-pending",
            source_name="Publisher D",
            when=now - timedelta(hours=1),
        ),
    ]
    private_contents = [
        _content(
            "private-canonical",
            owner_user_id=99,
            source_name="Private A",
            when=now - timedelta(hours=3),
        ),
        _content(
            "private-member",
            owner_user_id=99,
            source_name="Private B",
            when=now - timedelta(hours=2),
        ),
    ]
    db.add_all([*public_contents, *private_contents])
    await db.flush()

    public_group = ContentEventGroup(
        canonical_content_id=public_contents[0].id,
        owner_user_id=None,
        first_occurrence_at=public_contents[0].published_at,
        last_occurrence_at=public_contents[-1].published_at,
        status=EventStatus.ACTIVE,
    )
    private_group = ContentEventGroup(
        canonical_content_id=private_contents[0].id,
        owner_user_id=99,
        first_occurrence_at=private_contents[0].published_at,
        last_occurrence_at=private_contents[-1].published_at,
        status=EventStatus.ACTIVE,
    )
    db.add_all([public_group, private_group])
    await db.flush()

    member_specs = [
        (
            public_contents[1],
            EventRelationType.DUPLICATE,
            EventReviewStatus.AUTO,
        ),
        (
            public_contents[2],
            EventRelationType.CORROBORATION,
            EventReviewStatus.AUTO,
        ),
        (
            public_contents[3],
            EventRelationType.UPDATE,
            EventReviewStatus.CONFIRMED,
        ),
        (
            public_contents[4],
            EventRelationType.CORROBORATION,
            EventReviewStatus.PENDING,
        ),
    ]
    db.add_all(
        ContentEventMember(
            event_group_id=public_group.id,
            content_id=content.id,
            relation_type=relation,
            confidence=0.9,
            match_method="test",
            review_status=review,
        )
        for content, relation, review in member_specs
    )
    db.add(
        ContentEventMember(
            event_group_id=private_group.id,
            content_id=private_contents[1].id,
            relation_type=EventRelationType.CORROBORATION,
            confidence=0.92,
            match_method="test",
            review_status=EventReviewStatus.AUTO,
        )
    )
    await db.commit()
    return public_group, public_contents, private_group, private_contents


@pytest.mark.asyncio
async def test_today_pick_event_projection_is_batched_scoped_and_stable():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        public_group, public, private_group, private = await _seed_events(db)
        repo = ContentEventConsumptionRepository(db)
        statements: list[str] = []

        def count_statement(
            _connection,
            _cursor,
            statement,
            _parameters,
            _context,
            _executemany,
        ):
            statements.append(statement)

        event.listen(
            engine.sync_engine,
            "before_cursor_execute",
            count_statement,
        )

        public_assignments = await repo.resolve_today_pick_assignments(
            [item.id for item in [*public, *private]],
            visible_user_id=None,
        )
        assert len(statements) == 2
        assert set(public_assignments) == {
            public[0].id,
            public[1].id,
            public[2].id,
            public[3].id,
        }
        assert public_assignments[public[0].id].is_canonical is True
        assert public_assignments[public[2].id].relation_type == "corroboration"
        assert public[4].id not in public_assignments

        statements.clear()
        private_view = await repo.resolve_today_pick_assignments(
            [item.id for item in [*public, *private]],
            visible_user_id=99,
        )
        assert len(statements) == 2
        assert private[0].id in private_view
        assert private[1].id in private_view
        assert private_view[private[1].id].event_group_id == private_group.id

        statements.clear()
        groups = await repo.load_display_groups(
            [public_group.id],
            visible_user_id=None,
            member_limit=2,
        )
        assert len(statements) == 4
        summary = groups[public_group.id]
        assert summary.member_count == 3
        assert summary.source_count == 3
        assert [member.content_id for member in summary.members] == [
            public[1].id,
            public[2].id,
        ]
        assert [member.relation_type for member in summary.members] == [
            "duplicate",
            "corroboration",
        ]

    await engine.dispose()


@pytest.mark.asyncio
async def test_event_truth_evidence_marks_only_canonical_and_filters_relations(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        public_group, public, _private_group, _private = await _seed_events(db)
        monkeypatch.setattr(
            settings,
            "EVENT_NORMALIZATION_ROLLOUT_MODE",
            "serve",
        )
        stats = await discover_cross_source_evidence(
            db,
            hours=24,
            owner_user_id=None,
        )
        await db.commit()

        marks = list(
            (
                await db.execute(
                    select(ContentEvidenceMark).order_by(
                        ContentEvidenceMark.content_id
                    )
                )
            )
            .scalars()
            .all()
        )
        links = list(
            (
                await db.execute(
                    select(ContentEvidenceLink).order_by(
                        ContentEvidenceLink.evidence_content_id
                    )
                )
            )
            .scalars()
            .all()
        )

        assert stats["groups"] == 1
        assert stats["marks"] == 1
        assert stats["links"] == 2
        assert [mark.content_id for mark in marks] == [public[0].id]
        assert [link.evidence_content_id for link in links] == [
            public[2].id,
            public[3].id,
        ]
        assert [link.match_basis for link in links] == [
            "event:corroboration",
            "event:update",
        ]
        assert public_group.id == 1

    await engine.dispose()


def _pick_row(content_id: int, *, duplicate_of=None) -> dict:
    now = datetime.now(UTC).isoformat()
    return {
        "id": content_id,
        "title": f"pick-{content_id}",
        "url": f"https://example.com/pick-{content_id}",
        "source_id": content_id,
        "source_name": f"Source {content_id}",
        "source_type": "RSS",
        "platform": "rss",
        "published_at": now,
        "crawled_at": now,
        "category": "AI",
        "status": "analyzed",
        "duplicate_of": duplicate_of,
        "similarity_score": 0.9,
        "analysis_id": content_id,
        "analysis_created_at": now,
        "quality_score": 90.0,
        "hot_score": 80.0,
        "freshness_score": 90.0,
        "creator_score": 90.0,
        "viral_score": 80.0,
        "risk_score": 10.0,
        "curation_score": 90.0,
        "info_density": 90.0,
        "actionability": 90.0,
        "analysis_source_weight": 80.0,
        "source_weight_db": 5,
        "feedback_score": 0.0,
    }


@pytest.mark.asyncio
async def test_today_picks_serve_hides_all_event_members_and_reports_outside(
    monkeypatch,
    caplog,
):
    rows = [
        _pick_row(1, duplicate_of=999),
        _pick_row(2),
        _pick_row(3),
        _pick_row(4, duplicate_of=1),
    ]
    assignments = {
        1: EventAssignment(1, 10, 1, True),
        2: EventAssignment(2, 10, 1, False, "corroboration", 0.93),
        3: EventAssignment(3, 20, 99, False, "update", 0.91),
    }
    groups = {
        10: EventDisplayGroup(
            event_group_id=10,
            canonical_content_id=1,
            member_count=2,
            source_count=3,
            members=(
                EventDisplayMember(
                    content_id=2,
                    title="pick-2",
                    url="https://example.com/pick-2",
                    source_id=2,
                    source_name="Source 2",
                    source_type="RSS",
                    platform="rss",
                    published_at=datetime.now(UTC),
                    crawled_at=datetime.now(UTC),
                    relation_type="corroboration",
                    confidence=0.93,
                ),
            ),
        )
    }

    async def resolve(_self, _ids, *, visible_user_id):
        assert visible_user_id is None
        return assignments

    async def load_groups(
        _self,
        event_group_ids,
        *,
        visible_user_id,
        member_limit,
    ):
        assert set(event_group_ids) == {10}
        assert visible_user_id is None
        assert member_limit == 5
        return groups

    monkeypatch.setattr(
        settings,
        "EVENT_NORMALIZATION_ROLLOUT_MODE",
        "serve",
    )
    monkeypatch.setattr(
        today_picks,
        "query_today_picks",
        lambda **_kwargs: rows,
    )
    monkeypatch.setattr(today_picks, "query_topics", lambda: [])
    monkeypatch.setattr(
        ContentEventConsumptionRepository,
        "resolve_today_pick_assignments",
        resolve,
    )
    monkeypatch.setattr(
        ContentEventConsumptionRepository,
        "load_display_groups",
        load_groups,
    )

    with caplog.at_level("INFO", logger="app.services.today_picks"):
        payload = await today_picks.build_today_picks(
            object(),
            hours=48,
            limit=None,
        )

    assert [item["id"] for item in payload["items"]] == [1]
    assert payload["duplicates_hidden"] == 3
    assert "normalization_counters" not in payload
    assert today_picks._event_compare_counters(rows, assignments) == {
        "candidate_count": 4,
        "legacy_hidden": 2,
        "event_hidden": 2,
        "event_only_hidden": 2,
        "legacy_only_hidden": 2,
        "canonical_outside_window": 1,
    }
    assert "canonical_outside_window=1" in caplog.text
    normalization = payload["items"][0]["normalization"]
    assert normalization["member_count"] == 2
    assert normalization["has_more"] is True
    assert normalization["members"][0]["relation_type"] == "corroboration"


@pytest.mark.asyncio
async def test_today_picks_write_compares_without_changing_legacy_output(
    monkeypatch,
    caplog,
):
    rows = [_pick_row(1), _pick_row(2)]
    assignments = {
        1: EventAssignment(1, 10, 1, True),
        2: EventAssignment(2, 10, 1, False, "corroboration", 0.93),
    }

    async def resolve(_self, _ids, *, visible_user_id):
        assert visible_user_id is None
        return assignments

    async def must_not_expand(*_args, **_kwargs):
        raise AssertionError("write mode must not serve event expansion")

    monkeypatch.setattr(
        settings,
        "EVENT_NORMALIZATION_ROLLOUT_MODE",
        "write",
    )
    monkeypatch.setattr(
        today_picks,
        "query_today_picks",
        lambda **_kwargs: rows,
    )
    monkeypatch.setattr(today_picks, "query_topics", lambda: [])
    monkeypatch.setattr(
        ContentEventConsumptionRepository,
        "resolve_today_pick_assignments",
        resolve,
    )
    monkeypatch.setattr(
        ContentEventConsumptionRepository,
        "load_display_groups",
        must_not_expand,
    )

    with caplog.at_level("INFO", logger="app.services.today_picks"):
        payload = await today_picks.build_today_picks(object(), hours=48)

    assert {item["id"] for item in payload["items"]} == {1, 2}
    assert "normalization_counters" not in payload
    assert "event_hidden=1" in caplog.text


@pytest.mark.asyncio
async def test_today_picks_serve_query_error_falls_back_to_legacy(monkeypatch):
    rows = [_pick_row(1), _pick_row(2, duplicate_of=1)]

    async def fail_resolution(*_args, **_kwargs):
        raise RuntimeError("event truth unavailable")

    monkeypatch.setattr(
        settings,
        "EVENT_NORMALIZATION_ROLLOUT_MODE",
        "serve",
    )
    monkeypatch.setattr(
        today_picks,
        "query_today_picks",
        lambda **_kwargs: rows,
    )
    monkeypatch.setattr(today_picks, "query_topics", lambda: [])
    monkeypatch.setattr(
        ContentEventConsumptionRepository,
        "resolve_today_pick_assignments",
        fail_resolution,
    )

    payload = await today_picks.build_today_picks(object(), hours=48)

    assert [item["id"] for item in payload["items"]] == [1]
    assert payload["duplicates_hidden"] == 1
    assert "normalization_counters" not in payload
    assert payload["items"][0]["normalization"]["members"][0]["id"] == 2


def _evidence_content(
    content_id: int,
    *,
    source_id: int,
    family: str,
    relation_type: str | None = None,
    identity: str | None = None,
) -> EvidenceContent:
    return EvidenceContent(
        content_id=content_id,
        title=f"evidence-{content_id}",
        url=f"https://example.com/evidence-{content_id}",
        source_id=source_id,
        source_name=f"Source {source_id}",
        source_type="RSS",
        platform="website",
        published_at=datetime.now(UTC),
        crawled_at=datetime.now(UTC),
        publisher_identity=identity or f"Identity {source_id}",
        publisher_family=family,
        publisher_kind="publisher",
        official_domains=(),
        relation_type=relation_type,
        confidence=0.9,
    )


def test_event_evidence_deduplicates_publisher_family():
    event = EvidenceEvent(
        event_group_id=1,
        canonical=_evidence_content(1, source_id=1, family="Corp A"),
        evidence_members=(
            _evidence_content(
                2,
                source_id=2,
                family="Corp A",
                relation_type="corroboration",
            ),
            _evidence_content(
                3,
                source_id=3,
                family="Corp B",
                relation_type="update",
            ),
            _evidence_content(
                4,
                source_id=4,
                family="Corp B",
                relation_type="corroboration",
            ),
        ),
    )

    selected = evidence_service._event_evidence_members(event)

    assert [item.content_id for item in selected] == [3]


def test_event_evidence_deduplicates_publisher_identity_across_families():
    event = EvidenceEvent(
        event_group_id=1,
        canonical=_evidence_content(
            1,
            source_id=1,
            family="Family A",
            identity="Shared Publisher",
        ),
        evidence_members=(
            _evidence_content(
                2,
                source_id=2,
                family="Family B",
                identity="Shared Publisher",
                relation_type="corroboration",
            ),
            _evidence_content(
                3,
                source_id=3,
                family="Family C",
                identity="Independent Publisher",
                relation_type="update",
            ),
            _evidence_content(
                4,
                source_id=4,
                family="Family B",
                identity="Another Label",
                relation_type="corroboration",
            ),
        ),
    )

    selected = evidence_service._event_evidence_members(event)

    assert [item.content_id for item in selected] == [3]


def test_event_evidence_does_not_promote_unknown_publisher():
    unknown = EvidenceContent(
        content_id=2,
        title="unknown",
        url="https://example.com/unknown",
        source_id=None,
        source_name=None,
        source_type=None,
        platform=None,
        published_at=datetime.now(UTC),
        crawled_at=datetime.now(UTC),
        publisher_identity=None,
        publisher_family=None,
        publisher_kind=None,
        official_domains=(),
        relation_type="corroboration",
        confidence=0.9,
    )
    event = EvidenceEvent(
        event_group_id=1,
        canonical=_evidence_content(1, source_id=1, family="Known Corp"),
        evidence_members=(unknown,),
    )

    assert evidence_service._event_evidence_members(event) == []
    assert (
        evidence_service._get_platform(
            unknown.platform or unknown.source_type,
            unknown.source_name,
        )
        == "unknown"
    )


@pytest.mark.asyncio
async def test_unknown_canonical_platform_cannot_create_cross_source_evidence(
    monkeypatch,
):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        canonical = ContentItem(
            title="unknown canonical",
            url="https://example.com/unknown-canonical",
            source_id=None,
            source_name=None,
            source_type=None,
            platform="x",
            crawled_at=now - timedelta(hours=2),
            published_at=now - timedelta(hours=2),
            status=ContentStatus.ANALYZED,
            created_at=now - timedelta(hours=2),
            updated_at=now - timedelta(hours=2),
        )
        member = ContentItem(
            title="known publisher",
            url="https://example.com/known-publisher",
            source_id=None,
            source_name="Known Publisher",
            source_type="RSS",
            platform="website",
            crawled_at=now - timedelta(hours=1),
            published_at=now - timedelta(hours=1),
            status=ContentStatus.ANALYZED,
            created_at=now - timedelta(hours=1),
            updated_at=now - timedelta(hours=1),
        )
        db.add_all([canonical, member])
        await db.flush()
        group = ContentEventGroup(
            canonical_content_id=canonical.id,
            owner_user_id=None,
            first_occurrence_at=canonical.published_at,
            last_occurrence_at=member.published_at,
            status=EventStatus.ACTIVE,
        )
        db.add(group)
        await db.flush()
        db.add(
            ContentEventMember(
                event_group_id=group.id,
                content_id=member.id,
                relation_type=EventRelationType.CORROBORATION,
                confidence=0.95,
                match_method="test",
                review_status=EventReviewStatus.AUTO,
            )
        )
        await db.commit()

        monkeypatch.setattr(
            settings,
            "EVENT_NORMALIZATION_ROLLOUT_MODE",
            "serve",
        )
        stats = await discover_cross_source_evidence(
            db,
            hours=24,
            owner_user_id=None,
        )
        await db.commit()
        marks = list(
            (
                await db.execute(select(ContentEvidenceMark))
            )
            .scalars()
            .all()
        )

        assert stats["marks"] == 0
        assert stats["links"] == 0
        assert marks == []

    await engine.dispose()


@pytest.mark.asyncio
async def test_evidence_serve_error_falls_back_to_legacy(monkeypatch):
    async def fail_event(*_args, **_kwargs):
        raise RuntimeError("event truth unavailable")

    async def legacy(_db, *, hours, owner_user_id):
        assert hours == 24
        assert owner_user_id is None
        return {"groups": 7, "marks": 8, "links": 9, "total": 10}

    monkeypatch.setattr(
        settings,
        "EVENT_NORMALIZATION_ROLLOUT_MODE",
        "serve",
    )
    monkeypatch.setattr(
        evidence_service,
        "_discover_event_cross_source_evidence",
        fail_event,
    )
    monkeypatch.setattr(
        evidence_service,
        "_discover_legacy_cross_source_evidence",
        legacy,
    )

    stats = await discover_cross_source_evidence(object())

    assert stats == {
        "groups": 7,
        "marks": 8,
        "links": 9,
        "total": 10,
        "event_fallback": 1,
    }
