from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.selectable import Select

from app.core.database import Base
from app.models.monthly_digest import MonthlyDigest
from app.services import monthly_digest
from app.services.digest_base import DIGEST_GENERATING_STALE_AFTER
from app.services.monthly_digest import generate_monthly_digest


@pytest.mark.asyncio
async def test_generate_monthly_digest_returns_active_generating_without_fetch(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 6, 8, 12, 0, 0)
    monkeypatch.setattr(monthly_digest, "utc_now", lambda: now)

    async def fail_fetch(*_args, **_kwargs):
        raise AssertionError("active GENERATING digest should not fetch inputs")

    monkeypatch.setattr(monthly_digest, "fetch_analyzed_content_with_expanded_window", fail_fetch)
    async with session_factory() as db:
        existing = MonthlyDigest(
            month_key="2026-05",
            month_label="2026年5月",
            month_start="2026-05-01",
            month_end="2026-05-31",
            status="GENERATING",
            updated_at=now - timedelta(minutes=1),
        )
        db.add(existing)
        await db.commit()

        digest = await generate_monthly_digest(db, reference_date=date(2026, 6, 8))

    assert digest.id == existing.id
    assert digest.status == "GENERATING"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_monthly_digest_reclaims_stale_generating(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 6, 8, 12, 0, 0)
    monkeypatch.setattr(monthly_digest, "utc_now", lambda: now)

    async def fake_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(monthly_digest, "fetch_analyzed_content_with_expanded_window", fake_fetch)
    async with session_factory() as db:
        existing = MonthlyDigest(
            month_key="2026-05",
            month_label="2026年5月",
            month_start="2026-05-01",
            month_end="2026-05-31",
            status="GENERATING",
            updated_at=now - DIGEST_GENERATING_STALE_AFTER - timedelta(seconds=1),
        )
        db.add(existing)
        await db.commit()

        digest = await generate_monthly_digest(db, reference_date=date(2026, 6, 8))

    assert digest.id == existing.id
    assert digest.status == "ERROR"
    assert "暂无分析数据" in digest.overview
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_monthly_digest_locks_existing_row_for_postgresql(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 6, 8, 12, 0, 0)
    calls = {"for_update": 0}
    monkeypatch.setattr(monthly_digest, "utc_now", lambda: now)

    class FakeProfile:
        is_sqlite = False
        is_postgresql = True

    monkeypatch.setattr(monthly_digest, "database_profile", FakeProfile())
    original_with_for_update = Select.with_for_update

    def with_for_update_spy(self, *args, **kwargs):
        calls["for_update"] += 1
        return original_with_for_update(self, *args, **kwargs)

    async def fake_fetch(*_args, **_kwargs):
        return []

    monkeypatch.setattr(Select, "with_for_update", with_for_update_spy)
    monkeypatch.setattr(monthly_digest, "fetch_analyzed_content_with_expanded_window", fake_fetch)

    async with session_factory() as db:
        db.add(
            MonthlyDigest(
                month_key="2026-05",
                month_label="2026年5月",
                month_start="2026-05-01",
                month_end="2026-05-31",
                status="GENERATING",
                updated_at=now - DIGEST_GENERATING_STALE_AFTER - timedelta(seconds=1),
            )
        )
        await db.commit()

        digest = await generate_monthly_digest(db, reference_date=date(2026, 6, 8))

    assert calls["for_update"] == 1
    assert digest.status == "ERROR"
    await engine.dispose()
