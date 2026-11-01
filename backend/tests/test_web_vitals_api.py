"""/api/v1/metrics/web-vitals 端点回归测试（#179）。

覆盖：

- 上报端点**不要求登录**（登录页恰恰是最该被观测的页面），登录时可关联用户；
- 非法条目逐条丢弃，不整批失败、不 500；
- 条数上下限由 Pydantic 兜住（空数组 422，超过 50 条 422）；
- 聚合端点要求管理员：匿名 401、普通用户 403、管理员 200；
- 聚合返回 p75 与按路由的拆解。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.dashboard import router as dashboard_router
from app.api.v1 import auth as auth_api, web_vitals as web_vitals_api
from app.core.database import Base
from app.models.user import UserRole
from app.services.auth_service import create_session, create_user

Setup = tuple[httpx.AsyncClient, dict[str, str], async_sessionmaker[AsyncSession]]


@pytest_asyncio.fixture
async def web_vitals_api_setup() -> AsyncGenerator[Setup, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tokens: dict[str, str] = {}
    async with session_factory() as db:
        admin = await create_user(
            db,
            email="wv-admin@test.local",
            password="WebVitalsPass42!",
            role=UserRole.ADMIN.value,
        )
        token, _ = await create_session(db, admin)
        tokens["admin"] = token
        member = await create_user(db, email="wv-user@test.local", password="WebVitalsPass42!")
        token, _ = await create_session(db, member)
        tokens["user"] = token
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(web_vitals_api.router)
    # 大盘也要挂上：前端体验 Tab 落在那里（#179）
    app.include_router(dashboard_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[web_vitals_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tokens, session_factory

    await engine.dispose()


def _sample(metric: str = "LCP", value: float = 1200.0, path: str = "/") -> dict:
    return {
        "metric": metric,
        "value": value,
        "path": path,
        "navigation_type": "navigate",
        "device_class": "desktop",
    }


@pytest.mark.asyncio
async def test_report_accepts_without_login(web_vitals_api_setup: Setup):
    client, _, _ = web_vitals_api_setup
    resp = await client.post("/metrics/web-vitals", json={"samples": [_sample()]})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1, "rejected": 0}


@pytest.mark.asyncio
async def test_report_drops_invalid_entries_without_failing_batch(web_vitals_api_setup: Setup):
    client, _, _ = web_vitals_api_setup
    resp = await client.post(
        "/metrics/web-vitals",
        json={
            "samples": [
                _sample(value=1000.0),
                _sample(metric="UNKNOWN", value=1000.0),
                _sample(value=-5.0),
                _sample(metric="LCP", value=999_999.0),
            ]
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["accepted"] == 1
    assert body["rejected"] == 3


@pytest.mark.asyncio
async def test_report_rejects_empty_and_oversized_batches(web_vitals_api_setup: Setup):
    client, _, _ = web_vitals_api_setup
    resp = await client.post("/metrics/web-vitals", json={"samples": []})
    assert resp.status_code == 422

    resp = await client.post("/metrics/web-vitals", json={"samples": [_sample() for _ in range(21)]})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_report_drops_semantically_invalid_items_without_422(web_vitals_api_setup: Setup):
    """形状合法但语义非法的条目要逐条丢弃，不能让一笔脏数据把整批打成 422。

    schema 只做形状校验（是不是列表、字段在不在、条数超没超），
    语义判定（metric 白名单、路径归一后长度、枚举白名单）一律在 service 逐条做。
    """
    client, _, _ = web_vitals_api_setup
    resp = await client.post(
        "/metrics/web-vitals",
        json={
            "samples": [
                {"metric": "UNKNOWN_METRIC_XYZ", "value": 1200, "path": "/trending"},
                {"metric": "LCP", "value": 1200, "path": "/" + "a" * 300},
                {"metric": "LCP", "value": 1200, "path": "/trending"},
            ]
        },
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1, "rejected": 2}


@pytest.mark.asyncio
async def test_report_normalizes_empty_path_instead_of_rejecting_batch(
    web_vitals_api_setup: Setup,
):
    """空路径按 / 处理（service 归一），不该整批 422。"""
    client, tokens, _ = web_vitals_api_setup
    resp = await client.post(
        "/metrics/web-vitals",
        json={"samples": [{"metric": "LCP", "value": 1200, "path": ""}]},
    )
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 1, "rejected": 0}

    resp = await client.get(
        "/metrics/web-vitals/summary",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    )
    assert resp.status_code == 200
    assert {route["path"] for route in resp.json()["routes"]} == {"/"}


@pytest.mark.asyncio
async def test_report_swallows_db_failure_without_breaking_session(web_vitals_api_setup: Setup, monkeypatch):
    """DB 异常时不能把错误抛回浏览器，也不能把会话带坏。

    这条守卫最容易在重构中被删掉：删掉 try/except 后本用例会看到 500 而红。
    """
    client, tokens, _ = web_vitals_api_setup

    async def _boom(*args, **kwargs):
        raise RuntimeError("db is down")

    monkeypatch.setattr(web_vitals_api.web_vitals_service, "record_samples", _boom)

    resp = await client.post("/metrics/web-vitals", json={"samples": [_sample()]})
    assert resp.status_code == 202
    assert resp.json() == {"accepted": 0, "rejected": 1}

    # 守卫里带了回滚：随后的查询必须仍然可用，而不是连带 500
    resp = await client.get("/metrics/web-vitals/summary", headers={"Authorization": f"Bearer {tokens['admin']}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_summary_requires_admin(web_vitals_api_setup: Setup):
    client, tokens, _ = web_vitals_api_setup
    resp = await client.get("/metrics/web-vitals/summary")
    assert resp.status_code == 401

    resp = await client.get("/metrics/web-vitals/summary", headers={"Authorization": f"Bearer {tokens['user']}"})
    assert resp.status_code == 403

    resp = await client.get("/metrics/web-vitals/summary", headers={"Authorization": f"Bearer {tokens['admin']}"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_summary_returns_p75_and_route_breakdown(web_vitals_api_setup: Setup):
    client, tokens, _ = web_vitals_api_setup
    for value in (1000.0, 2000.0, 3000.0, 4000.0):
        await client.post("/metrics/web-vitals", json={"samples": [_sample(value=value, path="/topics/9")]})

    resp = await client.get(
        "/metrics/web-vitals/summary",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["sample_count"] == 4
    lcp = next(item for item in body["metrics"] if item["metric"] == "LCP")
    assert lcp["p75"] == 3000.0
    assert lcp["rating"] == "needs-improvement"
    assert {route["path"] for route in body["routes"]} == {"/topics/[id]"}


@pytest.mark.asyncio
async def test_summary_falls_back_to_navigate_for_unknown_navigation_type(
    web_vitals_api_setup: Setup,
):
    client, tokens, _ = web_vitals_api_setup
    resp = await client.get(
        "/metrics/web-vitals/summary?navigation_type=weird",
        headers={"Authorization": f"Bearer {tokens['admin']}"},
    )
    assert resp.status_code == 200
    assert resp.json()["navigation_type"] == "navigate"


@pytest.mark.asyncio
async def test_dashboard_exposes_web_vitals_tab(web_vitals_api_setup: Setup):
    """大盘是后端直出的大段 HTML 字符串，锚点写错不会有任何编译期报错。"""
    client, tokens, _ = web_vitals_api_setup

    assert (await client.get("/dashboard")).status_code in (401, 403)

    resp = await client.get("/dashboard", headers={"Authorization": f"Bearer {tokens['admin']}"})
    assert resp.status_code == 200
    html = resp.text
    assert 'data-tab="web-vitals"' in html
    assert "/api/v1/metrics/web-vitals/summary" in html
    assert 'id="wvRouteTable"' in html
    assert 'id="wvLcp"' in html
