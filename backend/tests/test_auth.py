from __future__ import annotations

import hashlib
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import auth as auth_api
from app.api.v1.auth import get_current_user, login, logout, me, register
from app.core.config import settings
from app.core.database import Base
from app.models.email_verification import EmailVerificationCode
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

# 测试用验证码常量
_TEST_VERIFICATION_CODE = "123456"


def _build_request(path: str = "/auth") -> Request:
    """构造测试用 Request 对象，供 register/login/logout 路由函数直接调用。

    路由签名 refactor 后新增 `request: Request` 参数（用于 client_ip 日志和限流），
    直接传 db 会导致 `client_ip(request)` 访问 `request.headers` 时报 AttributeError。

    参数:
        path: 请求路径（仅用于 Request.scope，不影响测试逻辑）
    """
    scope = {
        "type": "http",
        "client": ("127.0.0.1", 0),
        "headers": [],
        "query_string": b"",
        "path": path,
        "method": "POST",
    }
    return Request(scope)


async def _seed_verification_code(db: AsyncSession, email: str, code: str) -> None:
    """测试辅助：在内存 DB 中插入一条有效验证码记录，供 register 校验通过。

    参数:
        db: 数据库会话
        email: 注册邮箱（未归一化，内部归一化）
        code: 验证码明文
    """
    normalized = email.strip().lower()
    record = EmailVerificationCode(
        email=normalized,
        code_hash=hashlib.sha256(code.encode("utf-8")).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    db.add(record)
    await db.flush()


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
async def test_auth_route_functions_register_login_me_logout():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        # 注册前需先 seed 一条有效验证码记录，register 会校验
        await _seed_verification_code(db, "Route@Example.com", _TEST_VERIFICATION_CODE)
        registered = await register(
            AuthRegisterRequest(
                email="Route@Example.com",
                password="Password123",
                display_name="Route User",
                verification_code=_TEST_VERIFICATION_CODE,
            ),
            _build_request("/auth/register"),
            db,
        )
        assert registered.user.email == "route@example.com"
        assert registered.user.role == "user"
        assert registered.token_type == "bearer"

        # 重复注册：邮箱已存在，在验证码校验之前就 409 返回。
        # verification_code 字段仍需传（schema min_length=4），但不会被实际校验。
        duplicate_error = None
        try:
            await register(
                AuthRegisterRequest(
                    email="route@example.com",
                    password="Password123",
                    verification_code=_TEST_VERIFICATION_CODE,
                ),
                _build_request("/auth/register"),
                db,
            )
        except HTTPException as exc:
            duplicate_error = exc
        assert duplicate_error is not None
        assert duplicate_error.status_code == 409

        logged_in = await login(
            AuthLoginRequest(email="route@example.com", password="Password123"),
            _build_request("/auth/login"),
            db,
        )
        assert logged_in.user.role == "user"
        current_user = await get_current_user(f"Bearer {logged_in.access_token}", db)
        assert isinstance(current_user, User)
        assert (await me(current_user)).email == "route@example.com"

        assert (
            await logout(
                _build_request("/auth/logout"),
                f"Bearer {logged_in.access_token}",
                db,
            )
        )["logged_out"] is True
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
