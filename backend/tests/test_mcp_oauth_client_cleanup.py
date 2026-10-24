"""Client GC: disposable PostgreSQL only, no production/model requests."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from mcp.server.auth.provider import AuthorizationParams, AuthorizeError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.app_setting import AppSetting
from app.models.mcp_oauth import MCPOAuthAuthorization, MCPOAuthClient, MCPOAuthToken
from app.models.user import User
from app.repositories.mcp_oauth_client_repo import MCPOAuthClientRepository
from app.services import mcp_oauth_service as svc

NOW = datetime(2026, 10, 24, 12, tzinfo=UTC)
START = NOW - timedelta(days=30)
GC_KEY = "mcp_oauth_client_gc_started_at"


@pytest_asyncio.fixture
async def pg(monkeypatch):
    engine = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(svc, "_now", lambda: NOW)
    yield factory
    await engine.dispose()


def client(name, *, registered=None, seen=None):
    return MCPOAuthClient(
        client_id=name,
        client_name=name,
        metadata_json="{}",
        registered_at=registered or NOW - timedelta(days=8),
        last_seen_at=seen,
    )


def authorization(name, *, status="pending", expires=None):
    return MCPOAuthAuthorization(
        request_id=f"request-{name}",
        client_id=name,
        status=status,
        code_challenge="challenge",
        redirect_uri="http://127.0.0.1/cb",
        expires_at=expires or NOW + timedelta(minutes=10),
        updated_at=NOW - timedelta(days=2),
    )


async def set_start(db):
    db.add(AppSetting(key=GC_KEY, value=START.isoformat()))
    await db.flush()


@pytest.mark.asyncio
async def test_cleanup_preserves_legacy_active_and_ever_authorized_clients(pg):
    async with pg() as db:
        await set_start(db)
        db.add(User(id=1, email="gc@example.test", password_hash="not-a-live-password"))
        db.add_all(
            [
                client("orphan"),
                client("legacy", registered=START - timedelta(days=1)),
                client("young", registered=NOW - timedelta(days=6)),
                client("boundary", registered=NOW - timedelta(days=7)),
                client("seen", seen=NOW - timedelta(days=2)),
                client("pending"),
                client("approved"),
                client("token"),
            ]
        )
        await db.flush()
        db.add_all(
            [
                authorization("pending"),
                authorization("approved", status="consumed", expires=NOW - timedelta(days=2)),
                MCPOAuthToken(
                    token_hash="t" * 64,
                    token_type="refresh",
                    client_id="token",
                    user_id=1,
                    family_id="family",
                    expires_at=NOW - timedelta(days=2),
                    revoked_at=NOW - timedelta(days=2),
                ),
            ]
        )
        await db.commit()
        removed = await svc.cleanup_expired(db)
        await db.commit()
        assert removed["clients"] == 1
        assert removed["authorizations"] == removed["tokens"] == 1
        kept = (await db.execute(select(MCPOAuthClient).order_by(MCPOAuthClient.client_id))).scalars().all()
        assert {row.client_id for row in kept} == {
            "legacy",
            "young",
            "boundary",
            "seen",
            "pending",
            "approved",
            "token",
        }
        assert all(row.last_seen_at is not None for row in kept if row.client_id in {"approved", "token"})
        assert (await svc.cleanup_expired(db))["clients"] == 0
        await db.commit()


@pytest.mark.asyncio
async def test_first_cleanup_persists_boundary_and_keeps_unknown_history(pg):
    async with pg() as db:
        db.add(client("legacy-unknown", registered=NOW - timedelta(days=100)))
        await db.commit()
        assert (await svc.cleanup_expired(db))["clients"] == 0
        await db.commit()
        first = (await db.get(AppSetting, GC_KEY)).value
    async with pg() as db:
        assert (await svc.cleanup_expired(db))["clients"] == 0
        await db.commit()
        assert (await db.get(AppSetting, GC_KEY)).value == first
        assert await MCPOAuthClientRepository(db).get_by_client_id("legacy-unknown") is not None


def params():
    return AuthorizationParams(
        state="fixture",
        scopes=[],
        code_challenge="c" * 43,
        redirect_uri="http://127.0.0.1/cb",
        redirect_uri_provided_explicitly=True,
    )


@pytest.mark.asyncio
async def test_authorization_in_flight_wins_over_gc(pg):
    async with pg() as setup:
        await set_start(setup)
        setup.add(client("racing"))
        await setup.commit()
    async with pg() as writer, pg() as cleaner:
        await svc.create_authorization_request(writer, client_id="racing", params=params(), initiator_user_id=None)
        assert (await asyncio.wait_for(svc.cleanup_expired(cleaner), timeout=3))["clients"] == 0
        await cleaner.commit()
        await writer.commit()
    async with pg() as db:
        assert await MCPOAuthClientRepository(db).get_by_client_id("racing") is not None
        assert (
            await db.scalar(select(MCPOAuthAuthorization.id).where(MCPOAuthAuthorization.client_id == "racing"))
            is not None
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("commit_gc", [True, False])
async def test_gc_winner_never_leaves_a_dangling_authorization(pg, commit_gc):
    async with pg() as setup:
        await set_start(setup)
        setup.add(client("gc-wins"))
        await setup.commit()
    async with pg() as cleaner, pg() as writer:
        removed = await MCPOAuthClientRepository(cleaner).delete_stale(
            registered_since=START, older_than=NOW - timedelta(days=7)
        )
        assert removed == 1
        task = asyncio.create_task(
            svc.create_authorization_request(writer, client_id="gc-wins", params=params(), initiator_user_id=None)
        )
        try:
            # Both use a real parent row lock: creation cannot slip past an
            # uncommitted GC decision, even if SDK loaded client metadata earlier.
            await asyncio.sleep(0.05)
            assert not task.done()
            if commit_gc:
                await cleaner.commit()
                with pytest.raises(AuthorizeError, match="registration expired"):
                    await asyncio.wait_for(task, timeout=3)
                await writer.rollback()
            else:
                await cleaner.rollback()
                assert "request_id=" in await asyncio.wait_for(task, timeout=3)
                await writer.commit()
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    async with pg() as db:
        exists = await MCPOAuthClientRepository(db).get_by_client_id("gc-wins")
        request = await db.scalar(select(MCPOAuthAuthorization.id).where(MCPOAuthAuthorization.client_id == "gc-wins"))
        assert (exists is not None) == (request is not None) == (not commit_gc)


@pytest.mark.asyncio
async def test_batch_limit_and_rollback_leave_unselected_registrations_intact(pg):
    async with pg() as db:
        db.add_all([client(f"batch-{i}") for i in range(4)])
        await db.commit()
        repo = MCPOAuthClientRepository(db)
        assert await repo.delete_stale(registered_since=START, older_than=NOW - timedelta(days=7), limit=2) == 2
        await db.rollback()
        assert len((await db.scalars(select(MCPOAuthClient))).all()) == 4
        assert await repo.delete_stale(registered_since=START, older_than=NOW - timedelta(days=7), limit=2) == 2
        await db.commit()
        assert len((await db.scalars(select(MCPOAuthClient))).all()) == 2


@pytest.mark.asyncio
async def test_success_marker_is_persisted_at_token_issuance(pg):
    async with pg() as db:
        await set_start(db)
        db.add(client("success"))
        db.add(User(id=1, email="success@example.test", password_hash="fixture-only"))
        await db.commit()
        url = await svc.create_authorization_request(db, client_id="success", params=params(), initiator_user_id=1)
        code, _ = await svc.approve_authorization(db, url.split("request_id=")[1], 1)
        loaded = await svc.load_authorization_code(db, client_id="success", code=code)
        await svc.exchange_authorization_code(db, loaded)
        await db.commit()
        assert (await MCPOAuthClientRepository(db).get_by_client_id("success")).last_seen_at == NOW


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [None, "broken", "2026-10-01T00:00:00", "2026-10-25T12:00:00+00:00"])
async def test_invalid_boundary_aborts_without_removing_any_client(pg, invalid):
    async with pg() as db:
        db.add(AppSetting(key=GC_KEY, value=invalid))
        db.add(client("keep-on-error"))
        await db.commit()
        with pytest.raises(ValueError, match="start boundary"):
            await svc.cleanup_expired(db)
        await db.rollback()
        assert await MCPOAuthClientRepository(db).get_by_client_id("keep-on-error") is not None


@pytest.mark.asyncio
async def test_boundary_initialization_is_atomic_and_never_overwrites(pg):
    from app.repositories.app_setting_repo import AppSettingRepository

    async def initialize(value):
        async with pg() as db:
            row = await AppSettingRepository(db).get_or_create_setting(GC_KEY, value, "fixture")
            actual = row.value
            await db.commit()
            return actual

    one, two = await asyncio.gather(initialize(START.isoformat()), initialize(NOW.isoformat()))
    assert one == two and one in {START.isoformat(), NOW.isoformat()}


@pytest.mark.asyncio
@pytest.mark.parametrize("limit", [0, -1, 501])
async def test_gc_rejects_unbounded_batch_arguments(pg, limit):
    async with pg() as db:
        with pytest.raises(ValueError, match="1..500"):
            await MCPOAuthClientRepository(db).delete_stale(registered_since=START, older_than=NOW, limit=limit)


@pytest.mark.asyncio
async def test_gc_rejects_an_isolation_level_with_a_stale_snapshot(pg):
    async with pg() as db:
        db.add(client("repeatable-read"))
        await db.commit()
        await db.connection(execution_options={"isolation_level": "REPEATABLE READ"})
        with pytest.raises(RuntimeError, match="READ COMMITTED"):
            await MCPOAuthClientRepository(db).delete_stale(registered_since=START, older_than=NOW)
        await db.rollback()
    async with pg() as db:
        assert await MCPOAuthClientRepository(db).get_by_client_id("repeatable-read") is not None


@pytest.mark.asyncio
@pytest.mark.parametrize("fail", [True, False])
async def test_cleanup_job_status_and_client_counts_are_visible(monkeypatch, fail):
    from unittest.mock import AsyncMock, MagicMock

    from app import scheduler
    from app.services import job_tracker

    db = MagicMock()
    db.commit = AsyncMock()
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    counts = {"clients": 2, "authorizations": 3, "tokens": 4}
    cleanup = AsyncMock(side_effect=ValueError("invalid GC boundary") if fail else None, return_value=counts)
    finished = AsyncMock()
    released = AsyncMock()
    monkeypatch.setattr(scheduler, "async_session", lambda: context)
    monkeypatch.setattr(svc, "cleanup_expired", cleanup)
    monkeypatch.setattr(job_tracker, "_job_locks", {})
    monkeypatch.setattr(job_tracker, "_claim_job_run", AsyncMock(return_value=True))
    monkeypatch.setattr(job_tracker, "_create_log", AsyncMock(return_value=1))
    monkeypatch.setattr(job_tracker, "_finish_log", finished)
    monkeypatch.setattr(job_tracker, "_release_job_run", released)
    await scheduler._cleanup_mcp_oauth()
    expected = "FAILED" if fail else "SUCCESS"
    assert finished.call_args.args[1] == expected
    released.assert_awaited_once_with("cleanup_mcp_oauth", expected)
    if fail:
        assert "invalid GC boundary" in finished.call_args.kwargs["error_message"]
        db.commit.assert_not_awaited()
    else:
        import json

        assert json.loads(finished.call_args.kwargs["result_summary"]) == counts
        db.commit.assert_awaited_once()
