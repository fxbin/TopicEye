"""Event folding must preserve filtered scope, pagination and article access.

Uses the disposable PG from test_full_local.sh, including JSON tag filters and
the real event read locks. Never point this suite at a development database.
"""

import os
from datetime import UTC, datetime, timedelta

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.v1 import admin_content_events as admin_events_api, content_events as events_api, contents as contents_api
from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import ContentEventMember
from app.models.source import Source
from app.models.source_evidence_profile import SourceEvidenceProfile
from app.repositories.content_event_consumption_repo import ContentEventConsumptionRepository
from app.repositories.content_repo import ContentRepo
from app.services.auth_service import create_user
from app.services.content_event_coverage import attach_event_coverage, get_event_coverage
from app.services.content_event_service import ContentEventConflictError, ContentEventNotFoundError, ContentEventService
from app.services.content_list_cache import invalidate_content_list_cache
from app.services.scoring_engine import ScoringInput
from app.services.scoring_event_selection import display_event_candidate_ids


@pytest_asyncio.fixture
async def feed_db():
    # Own the engine, rather than reusing connections created by another
    # autouse fixture's event loop when this file is run in isolation.
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        yield db
        await db.rollback()
    await engine.dispose()


async def seed_feed(db):
    now = datetime.now(UTC)
    user = await create_user(db, email="coverage@example.com", password="Password123", role="user")
    source = Source(name="Official", url="https://official.example", source_type="RSS", status="active")
    db.add(source)
    await db.flush()
    db.add(
        SourceEvidenceProfile(
            source_id=source.id,
            publisher_identity="official",
            publisher_family="official",
            platform="web",
            publisher_kind="official",
            managed_by_admin=True,
            reviewed_at=now,
            official_domains=["official.example"],
        )
    )
    reports = []
    for index in range(9):
        item = ContentItem(
            title=f"report {index}" + (" special" if index == 4 else ""),
            url=f"https://official.example/report/{index}",
            source_id=source.id if index == 1 else None,
            source_name="Official" if index == 1 else f"Publisher {index}",
            source_type="RSS",
            status=ContentStatus.ANALYZED,
            category="AI",
            tags=["ai"] if index == 4 else [],
            published_at=now - timedelta(hours=10 - index),
            crawled_at=now - timedelta(hours=10 - index),
            created_at=now - timedelta(hours=10 - index),
        )
        db.add(item)
        await db.flush()
        reports.append(item)
        db.add(
            AiAnalysis(
                content_id=item.id,
                summary="A substantive analysis",
                summary_source="llm",
                quality_score=70,
                curation_score=75,
                recommend_level="值得观察",
            )
        )
    group = await ContentEventService(db).create_event([item.id for item in reports[:7]], owner_user_id=None)
    await ContentEventService(db).add_member(
        group.id, reports[7].id, review_status="pending", relation_type="duplicate"
    )
    await ContentEventService(db).add_member(
        group.id, reports[8].id, review_status="rejected", relation_type="duplicate"
    )
    private = ContentItem(
        title="private report",
        url="https://private.example/article",
        source_name="Private",
        source_type="RSS",
        owner_user_id=user.id,
        status=ContentStatus.ANALYZED,
        published_at=now,
        crawled_at=now,
        created_at=now,
    )
    db.add(private)
    await db.flush()
    await ContentEventService(db).create_event([private.id], owner_user_id=user.id)
    await db.flush()
    return reports, group, private, user


@pytest.mark.asyncio
async def test_group_before_page_counts_once_and_keeps_unaccepted_reports(feed_db):
    reports, group, private, user = await seed_feed(feed_db)
    repo = ContentRepo(feed_db)
    pages = []
    for page in (1, 2, 3):
        items, total = await repo.list_paginated_with_analyses(
            page=page, page_size=1, public_only=True, group_events=True
        )
        assert total == 3  # accepted event + pending + rejected
        pages.extend(item.id for item in items)
    assert set(pages) == {reports[1].id, reports[7].id, reports[8].id}
    assert len(pages) == len(set(pages)) == 3
    assert group.canonical_content_id == reports[0].id
    _, article_total = await repo.list_paginated_with_analyses(public_only=True)
    assert article_total == 9
    own, own_total = await repo.list_paginated_with_analyses(visible_user_id=user.id, group_events=True)
    assert own_total == 4 and private.id in {item.id for item in own}


@pytest.mark.asyncio
async def test_filter_can_choose_member_without_hiding_event(feed_db):
    reports, _, _, _ = await seed_feed(feed_db)
    for filters in ({"search_query": "special"}, {"tag": "AI"}, {"filters": {"source_name": "Publisher 4"}}):
        items, total = await ContentRepo(feed_db).list_paginated_with_analyses(
            public_only=True, group_events=True, **filters
        )
        assert total == 1 and [item.id for item in items] == [reports[4].id]
        payload = [{"id": reports[4].id}]
        await attach_event_coverage(feed_db, payload, visible_user_id=None)
        coverage = payload[0]["normalization"]
        assert coverage["member_count"] == 6
        assert reports[0].id in {item["id"] for item in coverage["members"]}
        assert reports[4].id not in {item["id"] for item in coverage["members"]}


@pytest.mark.asyncio
async def test_coverage_pages_include_original_and_reject_stale_version(feed_db):
    reports, group, private, user = await seed_feed(feed_db)
    first = await get_event_coverage(feed_db, reports[1].id, visible_user_id=None, member_offset=0, member_limit=5)
    assert first["has_more"] is True and first["next_offset"] == 5
    assert first["members"][0]["id"] == reports[0].id
    assert first["members"][0]["relation_type"] == "canonical"
    second = await get_event_coverage(
        feed_db,
        reports[1].id,
        visible_user_id=None,
        member_offset=first["next_offset"],
        member_limit=5,
        expected_event_id=first["event_id"],
        expected_version=first["version"],
    )
    assert second["has_more"] is False and second["next_offset"] == 6
    assert len({item["id"] for item in first["members"] + second["members"]}) == 6
    assert reports[1].id not in {item["id"] for item in first["members"] + second["members"]}
    assert all("reason" not in item and "confidence" not in item for item in first["members"])
    group.version += 1
    await feed_db.flush()
    with pytest.raises(ContentEventConflictError):
        await get_event_coverage(
            feed_db,
            reports[1].id,
            visible_user_id=None,
            member_offset=5,
            member_limit=5,
            expected_version=first["version"],
            expected_event_id=first["event_id"],
        )
    with pytest.raises(ContentEventNotFoundError):
        await get_event_coverage(feed_db, private.id, visible_user_id=None, member_offset=0, member_limit=5)
    own = await get_event_coverage(feed_db, private.id, visible_user_id=user.id, member_offset=0, member_limit=5)
    assert own is not None and own["member_count"] == 0


@pytest.mark.asyncio
async def test_pending_and_rejected_have_no_coverage_and_manual_canonical_wins(feed_db):
    reports, group, _, _ = await seed_feed(feed_db)
    for item in reports[7:]:
        assert await get_event_coverage(feed_db, item.id, visible_user_id=None, member_offset=0, member_limit=5) is None
    group.canonical_locked = True
    await feed_db.flush()
    items, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True, group_events=True)
    assert reports[0].id in {item.id for item in items}
    assert reports[1].id not in {item.id for item in items}


@pytest.mark.asyncio
async def test_latest_recommendation_controls_grouped_filter(feed_db):
    reports, _, _, _ = await seed_feed(feed_db)
    feed_db.add(
        AiAnalysis(
            content_id=reports[0].id,
            summary="Updated assessment",
            recommend_level="不建议追",
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    await feed_db.flush()
    items, total = await ContentRepo(feed_db).list_paginated_with_analyses(
        public_only=True, group_events=True, recommend_level="不建议追"
    )
    assert total == 1 and [item.id for item in items] == [reports[0].id]
    items, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True, recommend_level="值得观察")
    assert reports[0].id not in {item.id for item in items}


@pytest.mark.asyncio
async def test_pick_representative_prefers_primary_profile_and_preserves_coverage(feed_db):
    reports, group, _, _ = await seed_feed(feed_db)
    assignments = await ContentEventConsumptionRepository(feed_db).resolve_today_pick_assignments(
        [item.id for item in reports], visible_user_id=None
    )
    candidates = [ScoringInput(content_id=item.id, quality_score=70, curation_score=75) for item in reports[:7]]
    assert assignments[reports[1].id].display_is_primary is True
    assert display_event_candidate_ids(candidates, assignments) == {reports[1].id}
    # A time/source filter excluding the canonical still retains one visible report.
    assert display_event_candidate_ids(candidates[2:4], assignments) == {reports[2].id}
    payload = [{"id": reports[1].id}]
    await attach_event_coverage(feed_db, payload, visible_user_id=None, assignments=assignments)
    assert payload[0]["normalization"]["canonical_id"] == reports[0].id
    assert payload[0]["normalization"]["representative_id"] == reports[1].id
    assert payload[0]["normalization"]["member_count"] == 6
    assert group.canonical_content_id == reports[0].id


@pytest.mark.asyncio
async def test_locked_fallback_keeps_identity_but_formal_report_is_displayed(feed_db):
    reports, group, _, _ = await seed_feed(feed_db)
    feed_db.add(
        AiAnalysis(
            content_id=reports[0].id,
            summary_source="local_fallback",
            summary="Awaiting real analysis",
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    group.canonical_locked = True
    await feed_db.flush()
    items, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True, group_events=True)
    assert reports[1].id in {item.id for item in items}
    assert reports[0].id not in {item.id for item in items}
    assert group.canonical_content_id == reports[0].id and group.canonical_locked is True


@pytest.mark.asyncio
async def test_event_time_is_query_only_and_article_timestamp_is_preserved(feed_db):
    reports, _, _, _ = await seed_feed(feed_db)
    assert "event_activity_at" not in ContentItem.__table__.columns
    original_time = reports[1].published_at
    items, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True, group_events=True)
    representative = next(item for item in items if item.id == reports[1].id)
    assert representative.event_activity_at == reports[6].created_at
    assert representative.published_at == original_time
    articles, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True)
    assert all(item.event_activity_at is None for item in articles)


@pytest.mark.asyncio
async def test_thin_primary_report_does_not_suppress_substantive_secondary(feed_db):
    reports, _, _, _ = await seed_feed(feed_db)
    feed_db.add(
        AiAnalysis(
            content_id=reports[1].id,
            summary_source="llm",
            summary="Thin official brief",
            quality_score=10,
            curation_score=99,
            created_at=datetime.now(UTC) + timedelta(seconds=1),
        )
    )
    await feed_db.flush()
    items, _ = await ContentRepo(feed_db).list_paginated_with_analyses(public_only=True, group_events=True)
    assert reports[0].id in {item.id for item in items}
    assert reports[1].id not in {item.id for item in items}


@pytest.mark.asyncio
async def test_grouped_content_endpoint_preserves_article_view_and_coverage_contract(feed_db):
    reports, _, _, _ = await seed_feed(feed_db)
    invalidate_content_list_cache()
    app = FastAPI()
    app.include_router(contents_api.router)
    app.include_router(events_api.router)

    async def session():
        yield feed_db

    app.dependency_overrides[get_db] = session
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        grouped = await client.get("/contents?group_events=true&q=special")
        assert grouped.status_code == 200, grouped.text
        data = grouped.json()
        assert data["total"] == 1 and data["items"][0]["id"] == reports[4].id
        assert data["items"][0]["normalization"]["member_count"] == 6
        assert data["items"][0]["event_activity_at"] is not None
        articles = await client.get("/contents")
        assert articles.status_code == 200 and articles.json()["total"] == 9
        assert all(item["event_activity_at"] is None for item in articles.json()["items"])
        assert all("normalization" not in item for item in articles.json()["items"])
        assert (await client.get("/contents?group_events=true&sort_by=curation_score")).status_code == 400
    invalidate_content_list_cache()


@pytest.mark.asyncio
async def test_rejecting_a_member_immediately_restores_it_in_cached_home_feed(feed_db):
    from types import SimpleNamespace

    reports, group, _, user = await seed_feed(feed_db)
    invalidate_content_list_cache()
    app = FastAPI()
    app.include_router(contents_api.router)
    app.include_router(admin_events_api.router)

    async def session():
        yield feed_db

    app.dependency_overrides[get_db] = session
    app.dependency_overrides[get_current_admin_user] = lambda: SimpleNamespace(id=user.id, role="admin")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        before = await client.get("/contents?group_events=true")
        assert before.status_code == 200 and before.json()["total"] == 3
        assert (await client.get("/contents?group_events=true")).headers["x-content-list-cache"].startswith("HIT")
        member = await feed_db.scalar(select(ContentEventMember).where(ContentEventMember.content_id == reports[4].id))
        changed = await client.patch(
            f"/admin/content-events/members/{member.id}/review",
            json={"decision": "reject", "reason": "different event", "expected_version": group.version},
        )
        assert changed.status_code == 200, changed.text
        after = await client.get("/contents?group_events=true")
        assert after.status_code == 200 and after.json()["total"] == 4
        assert after.headers["x-content-list-cache"] == "MISS"
        restored = next(item for item in after.json()["items"] if item["id"] == reports[4].id)
        assert "normalization" not in restored
    invalidate_content_list_cache()
