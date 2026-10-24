"""Dataset exports use isolated PostgreSQL; never run against the business DB."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.content import ContentItem, ContentStatus
from app.services.auth_service import create_user
from app.services.content_event_dataset import export_public_event_pool
from app.services.content_event_service import ContentEventService


@pytest_asyncio.fixture
async def dataset_sessions():
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def seed_dataset(factory):
    now = datetime.now(UTC)
    async with factory() as db:
        user = await create_user(db, email="dataset-owner@example.com", password="Password123", role="user")
        items = []
        for i in range(7):
            item = ContentItem(
                title="PRIVATE_TITLE_SENTINEL" if i == 6 else f"Public report {i}",
                summary="PRIVATE_SUMMARY_SENTINEL" if i == 6 else "Public summary",
                raw_content="BODY_NOT_EXPORTED_SENTINEL",
                url=f"https://dataset.invalid/{i}",
                source_name="Publisher",
                source_type="RSS",
                owner_user_id=user.id if i == 6 else None,
                status=ContentStatus.ANALYZED,
                created_at=now + timedelta(days=1) if i == 5 else now - timedelta(hours=1),
                published_at=now - timedelta(hours=1),
                crawled_at=now - timedelta(hours=1),
            )
            db.add(item)
            await db.flush()
            items.append(item)
        groups = []
        for i in (0, 1):
            groups.append(await ContentEventService(db).create_event([items[i].id], owner_user_id=None))
        await ContentEventService(db).add_member(groups[0].id, items[4].id, review_status="rejected")
        await ContentEventService(db).create_event([items[6].id], owner_user_id=user.id)
        await db.commit()
        return [item.id for item in items]


@pytest.mark.asyncio
async def test_public_dataset_is_read_only_minimal_and_unlabeled(dataset_sessions):
    ids = await seed_dataset(dataset_sessions)
    async with dataset_sessions() as db:
        result = await export_public_event_pool(db, as_of=datetime.now(UTC), environment="isolated-test")
    assert {row["id"] for row in result["candidates"]} == set(ids[:2])
    assert {row["incoming"]["id"] for row in result["queries"]} == set(ids[2:4])
    assert result["provenance"]["transaction_read_only"] == "on"
    assert result["provenance"]["transaction_isolation"] == "repeatable read"
    assert not result["selection"]["pool_truncated"] and not result["selection"]["incoming_truncated"]
    assert all(row["expected"] == "unknown" and row["label_source"] == "unlabeled" for row in result["queries"])
    serialized = json.dumps(result)
    assert "PRIVATE_" not in serialized and "BODY_NOT_EXPORTED" not in serialized
    assert not result["human_holdout_verified"] and not result["write_rollout_eligible"]


@pytest.mark.asyncio
async def test_dataset_records_caps_instead_of_claiming_complete_pool(dataset_sessions):
    await seed_dataset(dataset_sessions)
    async with dataset_sessions() as db:
        result = await export_public_event_pool(
            db, as_of=datetime.now(UTC), environment="isolated-test", max_candidates=1, max_queries=1
        )
    assert len(result["candidates"]) == len(result["queries"]) == 1
    assert result["selection"]["pool_truncated"] and result["selection"]["incoming_truncated"]


@pytest.mark.asyncio
async def test_empty_actual_pool_stays_empty_and_export_needs_fresh_session(dataset_sessions):
    async with dataset_sessions() as db:
        result = await export_public_event_pool(db, as_of=datetime.now(UTC), environment="isolated-test")
        assert result["candidates"] == result["queries"] == []
        assert not result["write_rollout_eligible"]
        async with db.begin():
            with pytest.raises(ValueError, match="fresh session"):
                await export_public_event_pool(db, as_of=datetime.now(UTC), environment="isolated-test")
