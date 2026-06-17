"""Tests for user-owned daily reports (T2).

Covers the owner_user_id plumbing through:
  - generate_daily_report (apply owner + 透传到 inputs)
  - _fetch_report_inputs (visible_user_id 透传到 ContentRepo)
  - _claim_generation (per-owner idempotency via is_(None) filter)
  - get_latest_today_report (per-owner SELECT)
  - the /me/* FastAPI endpoints (plan gate + user isolation)
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.daily_report import DailyReport
from app.models.source import Source, SourceStatus, SourceType
from app.models.user import User
from app.services import daily_report as daily_report_svc
from app.services.daily_report import (
    generate_daily_report,
    get_latest_today_report,
)


@pytest.fixture(autouse=True)
def _restore_daily_report_module_state():
    """Snapshot & restore module-level symbols monkeypatched by the tests below."""
    import app.services.daily_report as svc

    saved = (
        svc._local_now,
        svc._fetch_report_inputs,
        svc.generate_daily_report,
    )
    yield
    svc._local_now = saved[0]
    svc._fetch_report_inputs = saved[1]
    svc.generate_daily_report = saved[2]


# ─── Service-layer tests ──────────────────────────────────────────────


async def _make_user(db: AsyncSession, *, id: int, plan: str = "pro") -> User:
    user = User(
        id=id,
        email=f"u{id}@x",
        password_hash="x",
        plan=plan,
        role="user",
        is_active=True,
        display_name=f"U{id}",
    )
    db.add(user)
    await db.flush()
    return user


async def _make_private_source(db: AsyncSession, *, id: int, owner_user_id: int) -> Source:
    src = Source(
        id=id,
        owner_user_id=owner_user_id,
        scope="user",
        name=f"priv-{id}",
        url=f"https://priv-{id}.com/rss",
        source_type=SourceType.RSS,
        status=SourceStatus.ACTIVE,
        weight=3,
        sort_order=0,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(src)
    await db.flush()
    return src


@pytest.mark.asyncio
async def test_generate_daily_report_persists_owner_user_id():
    """generate_daily_report should write owner_user_id to DailyReport row."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with sf() as db:
        await _make_user(db, id=42, plan="pro")
        await _make_private_source(db, id=100, owner_user_id=42)

    # Stub LLM-feeding helpers
    async def fake_inputs(db, *, window_start, window_end, visible_user_id=None):
        return [], []

    orig_fetch = daily_report_svc._fetch_report_inputs
    daily_report_svc._fetch_report_inputs = fake_inputs
    daily_report_svc._local_now = lambda: datetime(2026, 5, 27, 12, 0, 0)
    try:
        async with sf() as session:
            report = await generate_daily_report(
                session,
                target_date=date(2026, 5, 27),
                edition="noon",
                owner_user_id=42,
            )
            assert report.owner_user_id == 42
            assert report.status == "ERROR"  # no items → fallback ERROR
    finally:
        daily_report_svc._fetch_report_inputs = orig_fetch
    await engine.dispose()


@pytest.mark.asyncio
async def test_fetch_report_inputs_passes_visible_user_id_to_repo():
    """_fetch_report_inputs should forward visible_user_id to ContentRepo.list_for_report_window."""
    captured = {}

    class FakeContentRepo:
        def __init__(self, db):
            pass

        async def list_for_report_window(self, **kwargs):
            captured.update(kwargs)
            return []

    orig_repo = daily_report_svc.ContentRepo
    daily_report_svc.ContentRepo = FakeContentRepo
    try:
        from app.services import daily_report as dr
        from app.services.daily_report import _fetch_report_inputs

        result = await _fetch_report_inputs(
            __import__("app.core.database", fromlist=["async_session"]).async_session().__class__,
            window_start=datetime(2026, 5, 27, 0, 0, 0),
            window_end=datetime(2026, 5, 27, 12, 0, 0),
            visible_user_id=42,
        )
        assert captured.get("visible_user_id") == 42
    finally:
        daily_report_svc.ContentRepo = orig_repo


@pytest.mark.asyncio
async def test_claim_generation_isolates_per_owner():
    """Two users generating on the same day+edition should not share rows."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with sf() as db:
        await _make_user(db, id=10, plan="pro")
        await _make_user(db, id=11, plan="pro")

    async def fake_inputs(db, *, window_start, window_end, visible_user_id=None):
        # Generate a tiny but real curated/background set so report reaches DONE
        item = {
            "id": 1,
            "title": "T",
            "url": "u",
            "category": "c",
            "source_name": "s",
            "creator_score": 0.5,
            "viral_score": 0.5,
            "quality_score": 0.5,
            "risk_score": 0.1,
            "curation_score": 0.5,
            "adjusted_score": 0.5,
            "summary": "x",
            "recommendation": "",
        }
        return [item], [item]

    daily_report_svc._fetch_report_inputs = fake_inputs
    daily_report_svc._local_now = lambda: datetime(2026, 5, 27, 12, 0, 0)
    try:
        async with sf() as session:
            await generate_daily_report(
                session,
                target_date=date(2026, 5, 27),
                edition="noon",
                owner_user_id=10,
            )
            await generate_daily_report(
                session,
                target_date=date(2026, 5, 27),
                edition="noon",
                owner_user_id=11,
            )

        async with sf() as session:
            rows = (
                (await session.execute(select(DailyReport).where(DailyReport.report_date == "2026-05-27")))
                .scalars()
                .all()
            )
        assert len(rows) == 2
        owner_ids = {r.owner_user_id for r in rows}
        assert owner_ids == {10, 11}
    finally:
        daily_report_svc._fetch_report_inputs = __import__(
            "app.services.daily_report", fromlist=["_fetch_report_inputs"]
        )._fetch_report_inputs
    await engine.dispose()


@pytest.mark.asyncio
async def test_get_latest_today_report_filters_by_owner():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    today = date.today()
    iso = today.isoformat()
    async with sf() as db:
        # Public report (owner=None)
        db.add(
            DailyReport(
                report_date=iso,
                weekday="X",
                edition="snapshot",
                generated_at=datetime.now(timezone.utc),
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc),
                cutoff_at=datetime.now(timezone.utc),
                status="DONE",
                topic_count=1,
                content_count=1,
                analyzed_count=1,
                owner_user_id=None,
            )
        )
        # User A's report
        db.add(
            DailyReport(
                report_date=iso,
                weekday="X",
                edition="snapshot",
                generated_at=datetime.now(timezone.utc),
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc),
                cutoff_at=datetime.now(timezone.utc),
                status="DONE",
                topic_count=1,
                content_count=1,
                analyzed_count=1,
                owner_user_id=10,
            )
        )
        await db.commit()

    # Stub generate_daily_report so fallback does not insert a new row for owner=11
    orig_gen = daily_report_svc.generate_daily_report

    async def fake_gen(*args, **kwargs):
        return None  # treat "no report" as "no report"

    daily_report_svc.generate_daily_report = fake_gen
    try:
        async with sf() as session:
            public = await get_latest_today_report(session)  # None owner
            a = await get_latest_today_report(session, owner_user_id=10)
            b = await get_latest_today_report(session, owner_user_id=11)
        assert public is not None and public.owner_user_id is None
        assert a is not None and a.owner_user_id == 10
        assert b is None  # no owner=11 row, fallback returns None (stubbed)
    finally:
        daily_report_svc.generate_daily_report = orig_gen
    await engine.dispose()


# ─── API-layer tests (/me/*) ─────────────────────────────────────────


def _build_test_app():
    """Build a FastAPI app with the daily_reports router + auth dependency override."""
    from fastapi import FastAPI, Depends
    from app.api.v1 import daily_reports as daily_reports_mod
    from app.api.v1.auth import get_current_user
    from app.core.database import get_db

    app = FastAPI()
    app.include_router(daily_reports_mod.router)
    return app


@pytest.mark.asyncio
async def test_me_today_requires_pro_plan(tmp_path, monkeypatch):
    db_path = str(tmp_path / "me.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with sf() as db:
        await _make_user(db, id=10, plan="free")

    app = _build_test_app()
    user = User(id=10, email="a@x", password_hash="x", plan="free", role="user", is_active=True, display_name="A")
    from app.api.v1.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: user

    async def override_db():
        async with sf() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    from app.core.database import get_db

    app.dependency_overrides[get_db] = override_db
    daily_reports_svc_mod = daily_report_svc  # alias for type checker

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/daily-reports/me/today")
    assert resp.status_code == 403
    assert "Pro" in resp.text
    await engine.dispose()


@pytest.mark.asyncio
async def test_me_today_generates_user_owned_report(tmp_path):
    db_path = str(tmp_path / "me2.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    async with sf() as db:
        await _make_user(db, id=10, plan="pro")

    app = _build_test_app()
    user = User(id=10, email="a@x", password_hash="x", plan="pro", role="user", is_active=True, display_name="A")
    from app.api.v1.auth import get_current_user
    from app.core.database import get_db

    app.dependency_overrides[get_current_user] = lambda: user

    async def override_db():
        async with sf() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = override_db

    # Stub _fetch_report_inputs to avoid LLM
    async def fake_inputs(db, *, window_start, window_end, visible_user_id=None):
        return [], []

    orig_local_now2 = daily_report_svc._local_now
    daily_report_svc._fetch_report_inputs = fake_inputs
    daily_report_svc._local_now = lambda: datetime.now(timezone.utc)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://testserver") as client:
            resp = await client.get("/daily-reports/me/today")
        assert resp.status_code == 200
        data = resp.json()
        assert data["owner_user_id"] == 10
    finally:
        daily_report_svc._fetch_report_inputs = __import__(
            "app.services.daily_report", fromlist=["_fetch_report_inputs"]
        )._fetch_report_inputs
        daily_report_svc._local_now = orig_local_now2
    await engine.dispose()


@pytest.mark.asyncio
async def test_me_dates_lists_only_user_owned(tmp_path):
    """Other users' reports must not appear in /me/dates."""
    db_path = str(tmp_path / "me3.db")
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
    sf = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as c:
        await c.run_sync(Base.metadata.create_all)
    today = date.today()
    iso = today.isoformat()
    async with sf() as db:
        await _make_user(db, id=10, plan="pro")
        await _make_user(db, id=11, plan="pro")
        db.add(
            DailyReport(
                report_date=iso,
                weekday="X",
                edition="snapshot",
                generated_at=datetime.now(timezone.utc),
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc),
                cutoff_at=datetime.now(timezone.utc),
                status="DONE",
                topic_count=1,
                content_count=1,
                analyzed_count=1,
                owner_user_id=10,
            )
        )
        db.add(
            DailyReport(
                report_date=iso,
                weekday="X",
                edition="snapshot",
                generated_at=datetime.now(timezone.utc),
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc),
                cutoff_at=datetime.now(timezone.utc),
                status="DONE",
                topic_count=1,
                content_count=1,
                analyzed_count=1,
                owner_user_id=11,
            )
        )
        db.add(
            DailyReport(
                report_date=iso,
                weekday="X",
                edition="snapshot",
                generated_at=datetime.now(timezone.utc),
                window_start=datetime.now(timezone.utc),
                window_end=datetime.now(timezone.utc),
                cutoff_at=datetime.now(timezone.utc),
                status="DONE",
                topic_count=1,
                content_count=1,
                analyzed_count=1,
                owner_user_id=None,  # public
            )
        )
        await db.commit()

    app = _build_test_app()
    user_a = User(id=10, email="a@x", password_hash="x", plan="pro", role="user", is_active=True, display_name="A")
    from app.api.v1.auth import get_current_user
    from app.core.database import get_db

    app.dependency_overrides[get_current_user] = lambda: user_a

    async def override_db():
        async with sf() as s:
            try:
                yield s
                await s.commit()
            except Exception:
                await s.rollback()
                raise

    app.dependency_overrides[get_db] = override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.get("/daily-reports/me/dates")
    assert resp.status_code == 200
    dates = resp.json()["dates"]
    # Only the user-owned (id=10) report, not the public one and not user 11's
    assert len(dates) == 1
    await engine.dispose()
