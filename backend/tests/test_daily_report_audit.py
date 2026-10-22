"""Regression for #136: public isolation and frozen async generation identity."""

import os
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.auth import get_current_user
from app.api.v1.daily_reports import router
from app.core.database import get_db
from app.models.daily_report import DailyReport
from app.models.user import User
from app.services import daily_report_generation as generation


@pytest_asyncio.fixture
async def test_session_factory():
    """Exercise real timestamptz/date_trunc against the disposable test PG."""
    engine = create_async_engine(os.environ["DATABASE_URL"])
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


async def seed_reports(db):
    for uid in (1, 2):
        db.add(User(id=uid, email=f"daily-{uid}@example.com", password_hash="x", role="user", plan="pro"))
    await db.flush()
    reports = []
    for owner in (None, 1, 2):
        report = DailyReport(
            report_date="2026-10-21",
            weekday="周三",
            edition="final",
            status="DONE",
            cutoff_at=datetime(2026, 10, 21, 23, 59, 59),
            owner_user_id=owner,
            overview="public" if owner is None else f"private-{owner}",
        )
        db.add(report)
        reports.append(report)
    await db.commit()
    return reports


def client_for(db, plan="pro"):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=1, plan=plan)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.asyncio
async def test_public_list_and_total_exclude_all_private_reports(db):
    public, *_ = await seed_reports(db)
    async with client_for(db) as client:
        response = await client.get("/daily-reports")
    assert response.status_code == 200
    assert response.json()["total"] == 1
    assert [item["id"] for item in response.json()["items"]] == [public.id]


@pytest.mark.asyncio
async def test_version_reads_enforce_owner_and_plan(db):
    public, mine, other = await seed_reports(db)
    async with client_for(db) as client:
        assert (await client.get(f"/daily-reports/versions/{public.id}")).status_code == 200
        assert (await client.get(f"/daily-reports/versions/{mine.id}")).status_code == 404
        assert (await client.get(f"/daily-reports/me/versions/{mine.id}")).status_code == 200
        assert (await client.get(f"/daily-reports/me/versions/{other.id}")).status_code == 404
        assert (await client.get(f"/daily-reports/me/versions/{public.id}")).status_code == 404
    async with client_for(db, plan="free") as client:
        assert (await client.get(f"/daily-reports/me/versions/{mine.id}")).status_code == 403
        assert (await client.post("/daily-reports/me/generate-version")).status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["target_date=invalid", "cutoff_at=invalid", "edition=bogus"])
async def test_generate_bad_input_returns_422(db, query):
    async with client_for(db) as client:
        assert (await client.post("/daily-reports/generate-version?" + query)).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize("owner", [None, 1])
async def test_background_generation_reuses_placeholder_even_when_clock_advances(
    db, test_session_factory, monkeypatch, owner
):
    await seed_reports(db)
    pending = []
    monkeypatch.setattr(generation, "async_session", test_session_factory)
    monkeypatch.setattr(generation, "track_background_task", lambda coro, **kw: pending.append(coro))
    # Use a fixed final window, but deliberately run the real generator later.
    from app.services import daily_report as service

    monkeypatch.setattr(service, "_fetch_report_inputs", AsyncMock(return_value=([], [])))
    report = await generation.start_daily_report_generation(
        db,
        target_date=date(2026, 10, 20),
        edition="manual",
        cutoff_at=datetime(2026, 10, 20, 8, 0),
        owner_user_id=owner,
    )
    placeholder_id = report.id
    assert report.status == "GENERATING"
    assert report.cutoff_at.astimezone(UTC) == datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    await db.refresh(report)
    assert report.cutoff_at == datetime(2026, 10, 20, 0, 0, tzinfo=UTC)
    await pending.pop()
    await db.refresh(report)
    assert report.status == "ERROR"  # empty inputs, no LLM/network
    rows = (await db.execute(select(DailyReport).where(DailyReport.report_date == "2026-10-20"))).scalars().all()
    assert [(r.id, r.owner_user_id) for r in rows] == [(placeholder_id, owner)]


@pytest.mark.asyncio
async def test_repeated_start_does_not_spawn_another_active_job(db, monkeypatch):
    await seed_reports(db)
    pending = []
    monkeypatch.setattr(generation, "track_background_task", lambda coro, **kw: pending.append(coro))
    first = await generation.start_daily_report_generation(db, target_date=date(2026, 10, 20), edition="manual")
    second = await generation.start_daily_report_generation(db, target_date=date(2026, 10, 20), edition="manual")
    assert first.id == second.id
    assert len(pending) == 1
    for coro in pending:
        coro.close()


@pytest.mark.asyncio
async def test_background_failure_rolls_back_and_marks_the_same_row(db, test_session_factory, monkeypatch):
    await seed_reports(db)
    pending = []
    monkeypatch.setattr(generation, "async_session", test_session_factory)
    monkeypatch.setattr(generation, "track_background_task", lambda coro, **kw: pending.append(coro))
    monkeypatch.setattr(generation, "generate_daily_report", AsyncMock(side_effect=RuntimeError("worker failed")))
    report = await generation.start_daily_report_generation(db, target_date=date(2026, 10, 20), edition="final")
    await pending.pop()
    await db.refresh(report)
    assert report.status == "ERROR"
    assert "worker failed" in report.overview


@pytest.mark.asyncio
async def test_hourly_trends_filter_private_content_and_bound_history(db):
    from app.models.content import ContentItem
    from app.repositories.content_repo import ContentRepo

    await seed_reports(db)
    start = datetime(2026, 10, 19, 16, tzinfo=UTC)
    end = datetime(2026, 10, 21, 16, tzinfo=UTC)
    for index, (owner, timestamp) in enumerate(
        [
            (None, start),
            (1, start),
            (2, start),
            (None, end),
            (None, start - timedelta(seconds=1)),
        ]
    ):
        db.add(
            ContentItem(
                title="frozen trend",
                url=f"https://example.com/trend-{index}",
                owner_user_id=owner,
                crawled_at=timestamp,
                status="analyzed",
            )
        )
    await db.commit()
    repo = ContentRepo(db)
    public = await repo.count_hourly_by_title_keywords(["frozen"], start, end=end)
    mine = await repo.count_hourly_by_title_keywords(["frozen"], start, end=end, visible_user_id=1)
    assert sum(count for _, count in public) == 1
    assert sum(count for _, count in mine) == 2


def test_heat_delta_uses_shanghai_dates_and_zero_hour_buckets():
    from app.api.v1.daily_reports import _heat_delta_pct

    # UTC 16:00 is the start of the next Shanghai day. Two occupied hours must
    # still use the same 24-hour denominator as a day with just one occupied hour.
    raw = [
        (datetime(2026, 10, 19, 16, tzinfo=UTC), 4),
        (datetime(2026, 10, 19, 17, tzinfo=UTC), 4),
        (datetime(2026, 10, 20, 16, tzinfo=UTC), 4),
    ]
    assert _heat_delta_pct(raw, today_iso="2026-10-21") == -50.0
    assert _heat_delta_pct(raw, today_iso="2026-10-21", elapsed_hours=12) == 0.0


@pytest.mark.asyncio
async def test_private_report_never_reaches_shared_group_webhook(monkeypatch):
    from app.services import alerting, daily_report, notification_service

    send_alert = AsyncMock()
    notify = AsyncMock()
    monkeypatch.setattr(alerting, "send_alert", send_alert)
    monkeypatch.setattr(notification_service, "push_notification", notify)
    report = SimpleNamespace(owner_user_id=1, topic_count=1)
    assert (
        await daily_report.push_daily_report_webhook(
            report, [{"title": "private secret"}], "2026-10-21", "final", force=True
        )
        is False
    )
    await daily_report._push_daily_report_success(report, [], "2026-10-21", "final")
    await daily_report._push_daily_report_failure(RuntimeError("private source failed"), owner_user_id=1)
    send_alert.assert_not_called()
    assert [c.kwargs["target_user_ids"] for c in notify.call_args_list] == [[1], [1]]


@pytest.mark.asyncio
async def test_concurrent_public_requests_claim_one_job(db, test_session_factory, monkeypatch):
    import asyncio

    await seed_reports(db)
    pending = []
    monkeypatch.setattr(generation, "track_background_task", lambda coro, **kw: pending.append(coro))

    async def start():
        async with test_session_factory() as session:
            result = await generation.start_daily_report_generation(
                session,
                target_date=date(2026, 10, 20),
                edition="manual",
                cutoff_at=datetime(2026, 10, 20, 8),
            )
            return result.id

    try:
        ids = await asyncio.gather(start(), start())
        assert ids[0] == ids[1]
        assert len(pending) == 1
    finally:
        for coro in pending:
            coro.close()


@pytest.mark.asyncio
async def test_public_calendar_excludes_private_versions_and_private_only_days(db, monkeypatch):
    from app.api.v1 import daily_reports as api

    public, mine, other = await seed_reports(db)
    public.takeaway = "public summary"
    mine.takeaway = "private secret"
    mine.cutoff_at = datetime(2026, 10, 21, 23, 59, 59, 999999, tzinfo=UTC)
    other.takeaway = "other private secret"
    db.add(
        DailyReport(
            report_date="2026-10-20",
            weekday="周二",
            edition="final",
            status="DONE",
            owner_user_id=2,
            takeaway="private-only day",
            content_count=999,
        )
    )
    await db.commit()

    client = client_for(db)
    monkeypatch.setattr(api, "_local_today", lambda: date(2026, 10, 22))
    async with client:
        response = await client.get("/daily-reports/calendar?days=7")
    assert response.status_code == 200
    days = {day["report_date"]: day for day in response.json()["days"]}
    assert days["2026-10-21"]["takeaway"] == "public summary"
    assert days["2026-10-20"]["takeaway"] is None
    assert days["2026-10-20"]["content_count"] == 0
    assert days["2026-10-20"]["has_report"] is False
