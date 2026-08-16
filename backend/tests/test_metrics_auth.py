"""metrics / dashboard 监控端点的鉴权测试。

这些端点暴露运行日志（含用户邮箱/IP）、LLM 成本与业务规模数据，
必须要求管理员身份；匿名访问 401，普通用户 403，管理员 200。

按项目先例（见 test_analysis_recovery 的 event-loop 隔离修复），
用 per-test SQLite factory + ``dependency_overrides[get_db]`` 隔离，
避免复用模块级全局 engine 造成跨事件循环连接错乱。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.dashboard import router as dashboard_router
from app.api.v1 import metrics as metrics_api
from app.core.database import Base, get_db
from app.models.user import UserRole
from app.services.auth_service import create_session, create_user


@pytest_asyncio.fixture
async def monitored_app(monkeypatch) -> AsyncGenerator[tuple[FastAPI, async_sessionmaker], None]:
    """(app, session_factory)：metrics + dashboard 路由 + 隔离的 DB。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # metrics 端点内部直接使用模块级 async_session，需要一并替换
    monkeypatch.setattr(metrics_api, "async_session", session_factory)

    app = FastAPI()
    app.include_router(metrics_api.router)
    app.include_router(dashboard_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield app, session_factory
    await engine.dispose()


async def _seed_account(session_factory: async_sessionmaker, email: str, role: str) -> str:
    async with session_factory() as session:
        user = await create_user(
            session,
            email=email,
            password="MetricsAuditPass42!",
            role=role,
        )
        token, _ = await create_session(session, user)
        await session.commit()
        return token


async def _get(app: FastAPI, path: str, token: str | None = None) -> httpx.Response:
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get(path, headers=headers)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/metrics", "/metrics/snapshot", "/metrics/history", "/metrics/logs", "/metrics/llm-logs"]
)
async def test_metrics_endpoints_reject_anonymous(monitored_app, path: str):
    app, _ = monitored_app
    resp = await _get(app, path)
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path", ["/metrics", "/metrics/snapshot", "/metrics/history", "/metrics/logs", "/metrics/llm-logs"]
)
async def test_metrics_endpoints_reject_non_admin(monitored_app, path: str):
    app, session_factory = monitored_app
    token = await _seed_account(session_factory, "metrics-user@test.local", UserRole.USER.value)
    resp = await _get(app, path, token)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_metrics_prometheus_allows_admin(monitored_app):
    app, session_factory = monitored_app
    token = await _seed_account(session_factory, "metrics-admin@test.local", UserRole.ADMIN.value)
    resp = await _get(app, "/metrics", token)
    assert resp.status_code == 200
    assert "topiceye_content_recent_24h" in resp.text


@pytest.mark.asyncio
async def test_dashboard_requires_admin(monitored_app):
    app, session_factory = monitored_app

    resp = await _get(app, "/dashboard")
    assert resp.status_code == 401

    token = await _seed_account(session_factory, "metrics-user@test.local", UserRole.USER.value)
    resp = await _get(app, "/dashboard", token)
    assert resp.status_code == 403

    token = await _seed_account(session_factory, "metrics-admin@test.local", UserRole.ADMIN.value)
    resp = await _get(app, "/dashboard", token)
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" in resp.text
