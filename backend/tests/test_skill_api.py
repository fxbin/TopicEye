"""Tests for the /api/v1/skill/* read endpoints.

Verifies auth gating (401 without token), response wiring, and parameter
validation. Heavy service functions (build_today_picks, DuckDB) are monkeypatched
to keep these tests fast and independent of the analytical layer.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import skill as skill_api
from app.api.v1.auth import get_current_user
from app.core.database import Base, get_db
from app.models.user import User


def _fake_user() -> User:
    return User(id=1, email="agent@example.com", password_hash="hash")


@pytest_asyncio.fixture
async def skill_app() -> AsyncGenerator[tuple[FastAPI, object], None]:
    """A minimal FastAPI app with the skill router, get_db + auth overridden."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(skill_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = _fake_user

    yield app, session_factory
    await engine.dispose()


def _client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")


# ── Auth gating ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_endpoints_require_auth(skill_app):
    """Without get_current_user override, every skill endpoint must 401."""
    app, _ = skill_app
    # Remove the auth override so get_current_user runs for real (no token → 401)
    app.dependency_overrides.pop(get_current_user, None)
    async with _client(app) as client:
        for path in ("/skill/today-picks", "/skill/daily-report", "/skill/trends"):
            resp = await client.get(path)
            assert resp.status_code == 401, f"{path} should require auth, got {resp.status_code}"


# ── today-picks ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_today_picks_returns_payload(skill_app, monkeypatch):
    app, _ = skill_app

    async def fake_build(db, *, category=None, hours=48, limit=None):
        return {
            "items": [{"id": 1, "title": "选题 A", "analysis": {"adjusted_curation_score": 88}}],
            "total": 1,
            "event_members_hidden": 0,
            "topics": [],
            "page": 1,
            "page_size": 1,
        }

    monkeypatch.setattr(skill_api, "build_today_picks", fake_build)

    async with _client(app) as client:
        resp = await client.get("/skill/today-picks?hours=24&limit=5")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["title"] == "选题 A"
    assert body["page_size"] == 1


@pytest.mark.asyncio
async def test_skill_today_picks_rejects_out_of_range_params(skill_app):
    app, _ = skill_app
    async with _client(app) as client:
        # hours > 168
        assert (await client.get("/skill/today-picks?hours=999")).status_code == 422
        # limit < 1
        assert (await client.get("/skill/today-picks?limit=0")).status_code == 422


# ── daily-report ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_daily_report_today(skill_app, monkeypatch):
    app, _ = skill_app

    async def fake_latest(db, *, owner_user_id=None):
        from types import SimpleNamespace

        return SimpleNamespace(
            id=1,
            owner_user_id=owner_user_id,
            report_date="2026-07-15",
            weekday="周二",
            edition="noon",
            generated_at=None,
            window_start=None,
            window_end=None,
            cutoff_at=None,
            source_scope="curated",
            source_item_ids=None,
            overview="今日选题综述",
            takeaway=None,
            keywords=None,
            trends=None,
            top_picks=None,
            platform_tips=None,
            topic_count=0,
            content_count=0,
            analyzed_count=0,
            status="DONE",
            created_at=None,
            updated_at=None,
        )

    monkeypatch.setattr(skill_api, "get_latest_today_report", fake_latest)

    async with _client(app) as client:
        resp = await client.get("/skill/daily-report")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overview"] == "今日选题综述"
    assert body["report_date"] == "2026-07-15"


@pytest.mark.asyncio
async def test_skill_daily_report_by_date_404(skill_app, monkeypatch):
    app, _ = skill_app

    class FakeRepo:
        def __init__(self, db):
            pass

        async def get_by_date(self, report_date, edition=None, owner_user_id=None):
            return None

    monkeypatch.setattr(skill_api, "DailyReportRepository", FakeRepo)

    async with _client(app) as client:
        resp = await client.get("/skill/daily-report?date=2020-01-01")

    assert resp.status_code == 404


# ── trends ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_skill_trends_returns_merged_payload(skill_app, monkeypatch):
    app, _ = skill_app

    monkeypatch.setattr(skill_api.duckdb_service, "query_trend_topics", lambda days=7: [{"topic": "AI"}])
    monkeypatch.setattr(
        skill_api.duckdb_service, "query_keyword_cloud", lambda days=7, limit=50: [{"keyword": "agent", "count": 10}]
    )

    async with _client(app) as client:
        resp = await client.get("/skill/trends?days=7&limit=30")

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["days"] == 7
    assert body["topics"] == [{"topic": "AI"}]
    assert body["keywords"] == [{"keyword": "agent", "count": 10}]
    assert resp.headers["x-analytics-backend"] == "duckdb"


@pytest.mark.asyncio
async def test_skill_trends_duckdb_failure_returns_503(skill_app, monkeypatch):
    app, _ = skill_app

    def boom(*args, **kwargs):
        raise OSError("duckdb unavailable")

    monkeypatch.setattr(skill_api.duckdb_service, "query_trend_topics", boom)

    async with _client(app) as client:
        resp = await client.get("/skill/trends")

    assert resp.status_code == 503
    assert resp.json()["detail"] == "DuckDB analytical layer unavailable"
