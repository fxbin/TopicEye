from __future__ import annotations

import json
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401
from app.core.database import Base
from app.models.product_feedback import ProductUpdate
from app.services.product_updates import fingerprint, replace_updates, snapshot_updates

CATALOG = json.loads((Path(__file__).parents[1] / "app/data/release_notes.json").read_text())["records"]


@pytest_asyncio.fixture
async def release_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with factory() as db, db.begin():
        db.add(
            ProductUpdate(
                version="v0.4.0",
                title=None,
                description=None,
                status="planned",
                items=[{"title": "旧计划", "description": "原始计划需要完整恢复", "kind": "roadmap"}],
            )
        )
    async with factory() as db:
        yield db
    await engine.dispose()


def test_catalog_is_auditable_and_does_not_invent_production_dates():
    assert len(CATALOG) == 12
    assert len({r["version"] for r in CATALOG}) == len(CATALOG)
    for record in CATALOG:
        assert record["title"] and record["summary"]
        assert 3 <= len(record["items"]) <= 5
        assert record["shipped_at"] is None
        assert record["evidence"]
        assert all(len(source["commit"]) == 40 for source in record["evidence"])


@pytest.mark.asyncio
async def test_rebuild_and_restore_preserve_original_rows(release_db):
    db = release_db
    before = await snapshot_updates(db)
    after = await replace_updates(db, CATALOG, expected=fingerprint(before))
    assert len(after) == 12
    assert all(row["title"] and row["description"] for row in after)
    assert all(row["shipped_at"] is None for row in after)
    restored = await replace_updates(db, before, expected=fingerprint(after), restore=True)
    assert restored == before


@pytest.mark.asyncio
async def test_stale_plan_cannot_overwrite_edits(release_db):
    before = await snapshot_updates(release_db)
    with pytest.raises(ValueError, match="已变化"):
        await replace_updates(release_db, CATALOG, expected="not-current")
    assert await snapshot_updates(release_db) == before


@pytest.mark.asyncio
async def test_invalid_catalog_does_not_delete_existing_records(release_db):
    before = await snapshot_updates(release_db)
    invalid = [*CATALOG, {**CATALOG[0], "title": ""}]
    with pytest.raises(ValueError):
        await replace_updates(release_db, invalid, expected=fingerprint(before))
    assert await snapshot_updates(release_db) == before


@pytest.mark.asyncio
async def test_postgres_rebuild_transaction_can_roll_back():
    from app.core.database import async_session

    async with async_session() as db:
        if db.bind.dialect.name != "postgresql":
            pytest.skip("requires disposable PostgreSQL")
        db.add(
            ProductUpdate(
                version="2026.01.01", title="原记录", description="需要在异常时完整保留", status="shipped", items=[]
            )
        )
        await db.commit()
        before = await snapshot_updates(db)
        await db.rollback()
        with pytest.raises(RuntimeError, match="simulate interruption"):
            async with db.begin():
                result = await replace_updates(db, CATALOG, expected=fingerprint(before))
                assert len(result) == 12
                raise RuntimeError("simulate interruption")
        assert await snapshot_updates(db) == before
        await db.rollback()
        async with db.begin():
            after = await replace_updates(db, CATALOG, expected=fingerprint(before))
            restored = await replace_updates(db, before, expected=fingerprint(after), restore=True)
            assert restored == before


@pytest.mark.asyncio
async def test_normalized_versions_cannot_duplicate(release_db):
    before = await snapshot_updates(release_db)
    duplicate = [{**CATALOG[0], "version": "2026-11-02"}, CATALOG[0]]
    with pytest.raises(ValueError, match="不能重复"):
        await replace_updates(release_db, duplicate, expected=fingerprint(before))
    assert await snapshot_updates(release_db) == before


def test_snapshot_covers_every_storage_column():
    from app.services.product_updates import _FIELDS

    assert set(_FIELDS) == set(ProductUpdate.__table__.columns.keys())
