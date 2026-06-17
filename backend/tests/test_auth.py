from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import auth as auth_api
from app.api.v1.auth import get_current_user, login, logout, me, register
from app.core.config import settings
from app.core.database import Base
from app.models.user import User
from app.schemas.auth import AuthLoginRequest, AuthRegisterRequest
from app.services.auth_service import (
    authenticate_user,
    create_session,
    create_user,
    ensure_admin_user,
    get_user_for_token,
    revoke_token,
    verify_password,
)


class _FakeSessionLookupResult:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _ReadOnlyTokenLookupSession:
    def __init__(self, user):
        self.user = user
        self.execute_count = 0

    async def execute(self, _statement):
        self.execute_count += 1
        return _FakeSessionLookupResult((101, self.user.id))

    async def flush(self):
        raise AssertionError("token lookup should not write last_seen_at")

    async def rollback(self):
        raise AssertionError("token lookup should not need rollback")

    async def get(self, model, user_id):
        assert model is User
        assert user_id == self.user.id
        return self.user


class _LockedCreateSessionDb:
    def __init__(self):
        self.add_count = 0
        self.flush_count = 0
        self.refresh_count = 0
        self.rollback_count = 0

    def add(self, item):
        self.add_count += 1
        self.item = item

    async def flush(self):
        self.flush_count += 1
        if self.flush_count == 1:
            raise OperationalError("INSERT user_sessions", {}, Exception("database is locked"))

    async def refresh(self, item):
        self.refresh_count += 1
        assert item is self.item

    async def rollback(self):
        self.rollback_count += 1


@pytest.mark.asyncio
async def test_auth_service_registers_lowercase_email_and_hashes_password():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="Codex@Example.COM", password="Password123", display_name=None)

        assert user.email == "codex@example.com"
        assert user.display_name == "codex"
        assert user.role == "user"
        assert user.password_hash != "Password123"
        assert verify_password("Password123", user.password_hash)
        assert not verify_password("wrong-password", user.password_hash)

    await engine.dispose()


@pytest.mark.asyncio
async def test_auth_service_session_lifecycle():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="session@example.com", password="Password123")
        token, session = await create_session(db, user)

        assert session.token_hash != token
        assert await authenticate_user(db, email="SESSION@example.com", password="Password123") is not None
        assert await authenticate_user(db, email="session@example.com", password="bad") is None

        current_user = await get_user_for_token(db, token)
        assert current_user is not None
        assert current_user.email == "session@example.com"

        assert await revoke_token(db, token) is True
        assert await get_user_for_token(db, token) is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_user_for_token_does_not_write_last_seen():
    user = User(id=7, email="readonly@example.com", password_hash="hash", display_name="Readonly")
    db = _ReadOnlyTokenLookupSession(user)

    current_user = await get_user_for_token(db, "session-token")

    assert current_user is user
    assert db.execute_count == 1


@pytest.mark.asyncio
async def test_create_session_retries_sqlite_locked_insert():
    user = User(id=7, email="locked@example.com", password_hash="hash", display_name="Locked")
    db = _LockedCreateSessionDb()

    token, session = await create_session(db, user)

    assert token
    assert session.user_id == user.id
    assert db.add_count == 2
    assert db.flush_count == 2
    assert db.refresh_count == 1
    assert db.rollback_count == 1


@pytest.mark.asyncio
async def test_auth_route_functions_register_login_me_logout():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        registered = await register(
            AuthRegisterRequest(email="Route@Example.com", password="Password123", display_name="Route User"),
            db,
        )
        assert registered.user.email == "route@example.com"
        assert registered.user.role == "user"
        assert registered.token_type == "bearer"

        duplicate_error = None
        try:
            await register(AuthRegisterRequest(email="route@example.com", password="Password123"), db)
        except HTTPException as exc:
            duplicate_error = exc
        assert duplicate_error is not None
        assert duplicate_error.status_code == 409

        logged_in = await login(AuthLoginRequest(email="route@example.com", password="Password123"), db)
        assert logged_in.user.role == "user"
        current_user = await get_current_user(f"Bearer {logged_in.access_token}", db)
        assert isinstance(current_user, User)
        assert (await me(current_user)).email == "route@example.com"

        assert (await logout(f"Bearer {logged_in.access_token}", db))["logged_out"] is True
        invalid_error = None
        try:
            await get_current_user(f"Bearer {logged_in.access_token}", db)
        except HTTPException as exc:
            invalid_error = exc
        assert invalid_error is not None
        assert invalid_error.status_code == 401

    await engine.dispose()


@pytest.mark.asyncio
async def test_login_route_rate_limits_repeated_attempts(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_LOGIN_ATTEMPTS_PER_MINUTE", 1)
    auth_api._AUTH_RATE_BUCKETS.clear()

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        await create_user(db, email="limited@example.com", password="Password123")
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            first = await client.post(
                "/auth/login",
                json={"email": "limited@example.com", "password": "wrong"},
            )
            assert first.status_code == 401

            second = await client.post(
                "/auth/login",
                json={"email": "limited@example.com", "password": "wrong"},
            )
            assert second.status_code == 429
    finally:
        auth_api._AUTH_RATE_BUCKETS.clear()
        await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_admin_user_creates_builtin_admin():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        admin = await ensure_admin_user(
            db,
            email="Admin@TopicEye.Local",
            password="TopicEyeAdmin123!",
            display_name="TopicEye 管理员",
        )

        assert admin.email == "admin@topiceye.local"
        assert admin.display_name == "TopicEye 管理员"
        assert admin.role == "admin"
        assert admin.is_active is True
        assert (
            await authenticate_user(
                db,
                email="admin@topiceye.local",
                password="TopicEyeAdmin123!",
            )
            is admin
        )

    await engine.dispose()


@pytest.mark.asyncio
async def test_ensure_admin_user_promotes_existing_account_without_resetting_password():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(
            db,
            email="admin@topiceye.local",
            password="CustomPassword123",
            display_name="Custom Admin",
        )
        user.is_active = False
        await db.flush()

        admin = await ensure_admin_user(
            db,
            email="admin@topiceye.local",
            password="TopicEyeAdmin123!",
            display_name="TopicEye 管理员",
        )

        assert admin.id == user.id
        assert admin.role == "admin"
        assert admin.is_active is True
        assert admin.display_name == "Custom Admin"
        assert (
            await authenticate_user(
                db,
                email="admin@topiceye.local",
                password="CustomPassword123",
            )
            is admin
        )
        assert (
            await authenticate_user(
                db,
                email="admin@topiceye.local",
                password="TopicEyeAdmin123!",
            )
            is None
        )

    await engine.dispose()
