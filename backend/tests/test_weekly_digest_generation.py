from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.selectable import Select

from app.core.database import Base
from app.models.weekly_digest import WeeklyDigest
from app.services import weekly_digest
from app.services.digest_base import DIGEST_GENERATING_STALE_AFTER
from app.services.weekly_digest import generate_weekly_digest


@pytest.mark.asyncio
async def test_generate_weekly_digest_returns_active_generating_without_fetch(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    monkeypatch.setattr(weekly_digest, "utc_now", lambda: now)

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("active GENERATING digest should not fetch inputs")

    monkeypatch.setattr(weekly_digest, "_fetch_weekly_analyzed", fail_fetch)
    async with session_factory() as db:
        existing = WeeklyDigest(
            week_key="2026-W21",
            week_label="5月18日 ~ 5月24日",
            week_start="2026-05-18",
            week_end="2026-05-24",
            status="GENERATING",
            updated_at=now - timedelta(minutes=1),
        )
        db.add(existing)
        await db.commit()

        digest = await generate_weekly_digest(db, reference_date=date(2026, 5, 27))

    assert digest.id == existing.id
    assert digest.status == "GENERATING"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_weekly_digest_reclaims_stale_generating(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    monkeypatch.setattr(weekly_digest, "utc_now", lambda: now)

    async def fake_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(weekly_digest, "_fetch_weekly_analyzed", fake_fetch)
    async with session_factory() as db:
        existing = WeeklyDigest(
            week_key="2026-W21",
            week_label="5月18日 ~ 5月24日",
            week_start="2026-05-18",
            week_end="2026-05-24",
            status="GENERATING",
            updated_at=now - DIGEST_GENERATING_STALE_AFTER - timedelta(seconds=1),
        )
        db.add(existing)
        await db.commit()

        digest = await generate_weekly_digest(db, reference_date=date(2026, 5, 27))

    assert digest.id == existing.id
    assert digest.status == "ERROR"
    assert "暂无分析数据" in digest.overview
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_weekly_digest_retries_sqlite_claim_lock(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    calls = {"begin": 0}
    monkeypatch.setattr(weekly_digest, "utc_now", lambda: now)

    async def flaky_begin_immediate(_db):
        calls["begin"] += 1
        if calls["begin"] == 1:
            raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    async def fake_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(weekly_digest, "begin_immediate_for_sqlite", flaky_begin_immediate)
    monkeypatch.setattr(weekly_digest, "_fetch_weekly_analyzed", fake_fetch)

    # sqlite claim lock 重试路径: 必须 is_sqlite=True 才会进 begin_immediate 分支
    class FakeProfile:
        is_sqlite = True
        is_postgresql = False

    monkeypatch.setattr(weekly_digest, "database_profile", FakeProfile())

    async with session_factory() as db:
        digest = await generate_weekly_digest(db, reference_date=date(2026, 5, 27))

    assert calls["begin"] == 2
    assert digest.status == "ERROR"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_weekly_digest_locks_existing_row_for_postgresql(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    calls = {"for_update": 0}
    monkeypatch.setattr(weekly_digest, "utc_now", lambda: now)

    class FakeProfile:
        is_sqlite = False
        is_postgresql = True

    monkeypatch.setattr(weekly_digest, "database_profile", FakeProfile())
    original_with_for_update = Select.with_for_update

    def with_for_update_spy(self, *args, **kwargs):
        calls["for_update"] += 1
        return original_with_for_update(self, *args, **kwargs)

    async def fake_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(Select, "with_for_update", with_for_update_spy)
    monkeypatch.setattr(weekly_digest, "_fetch_weekly_analyzed", fake_fetch)

    async with session_factory() as db:
        db.add(
            WeeklyDigest(
                week_key="2026-W21",
                week_label="5月18日 ~ 5月24日",
                week_start="2026-05-18",
                week_end="2026-05-24",
                status="GENERATING",
                updated_at=now - DIGEST_GENERATING_STALE_AFTER - timedelta(seconds=1),
            )
        )
        await db.commit()

        digest = await generate_weekly_digest(db, reference_date=date(2026, 5, 27))

    assert calls["for_update"] == 1
    assert digest.status == "ERROR"
    await engine.dispose()
