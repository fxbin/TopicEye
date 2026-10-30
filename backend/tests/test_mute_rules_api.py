"""/api/v1/mute-rules CRUD 回归测试（#171）。

覆盖：未登录 401；创建/列表/删除主流程；重复创建 409；非法 value 422；
非法 rule_type 422；每类上限 50；只能删自己的规则。

走内存 SQLite（快；mute_rules 无 PG 专属约束依赖）。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, mute_rules as mute_rules_api
from app.core.database import Base
from app.services.auth_service import create_session, create_user

Setup = tuple[httpx.AsyncClient, dict[str, str], async_sessionmaker[AsyncSession]]


@pytest_asyncio.fixture
async def mute_api_setup() -> AsyncGenerator[Setup, None]:
    from app.services.content_read_cache import invalidate_content_read_caches

    invalidate_content_read_caches()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    tokens: dict[str, str] = {}
    async with session_factory() as db:
        for name in ("alice", "bob"):
            user = await create_user(db, email=f"{name}@example.com", password="Password123")
            token, _ = await create_session(db, user)
            tokens[name] = token
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(mute_rules_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[mute_rules_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, tokens, session_factory

    await engine.dispose()
    invalidate_content_read_caches()


@pytest.mark.asyncio
async def test_requires_auth(mute_api_setup: Setup):
    client, _, _ = mute_api_setup
    resp = await client.get("/mute-rules")
    assert resp.status_code in (401, 403)
    resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": "x"})
    assert resp.status_code in (401, 403)
    resp = await client.delete("/mute-rules/1")
    assert resp.status_code in (401, 403)


@pytest.mark.asyncio
async def test_create_list_delete_roundtrip(mute_api_setup: Setup):
    client, tokens, _ = mute_api_setup
    headers = {"Authorization": f"Bearer {tokens['alice']}"}

    resp = await client.post(
        "/mute-rules",
        json={"rule_type": "domain", "value": "https://www.Noisy.example.com/a"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    created = resp.json()
    assert created["rule_type"] == "domain"
    assert created["value"] == "noisy.example.com", "写入前应归一去 www./协议/路径"
    assert created["id"] > 0
    assert created["created_at"]

    await client.post("/mute-rules", json={"rule_type": "keyword", "value": "静音词"}, headers=headers)
    await client.post("/mute-rules", json={"rule_type": "source", "value": "007"}, headers=headers)

    resp = await client.get("/mute-rules", headers=headers)
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 3
    values = {(item["rule_type"], item["value"]) for item in payload["items"]}
    assert ("domain", "noisy.example.com") in values
    assert ("keyword", "静音词") in values
    assert ("source", "7") in values, "source 值应归一为无前导零的数字字符串"

    rule_id = next(item["id"] for item in payload["items"] if item["rule_type"] == "domain")
    resp = await client.delete(f"/mute-rules/{rule_id}", headers=headers)
    assert resp.status_code == 204
    # 再删同一 id → 404
    resp = await client.delete(f"/mute-rules/{rule_id}", headers=headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_rules_are_per_user(mute_api_setup: Setup):
    client, tokens, _ = mute_api_setup
    alice = {"Authorization": f"Bearer {tokens['alice']}"}
    bob = {"Authorization": f"Bearer {tokens['bob']}"}

    resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": "secret"}, headers=alice)
    rule_id = resp.json()["id"]

    resp = await client.get("/mute-rules", headers=bob)
    assert resp.json()["count"] == 0, "Bob 不应看到 Alice 的规则"

    resp = await client.delete(f"/mute-rules/{rule_id}", headers=bob)
    assert resp.status_code == 404, "Bob 不应能删 Alice 的规则"

    resp = await client.get("/mute-rules", headers=alice)
    assert resp.json()["count"] == 1


@pytest.mark.asyncio
async def test_duplicate_create_returns_409(mute_api_setup: Setup):
    client, tokens, _ = mute_api_setup
    headers = {"Authorization": f"Bearer {tokens['alice']}"}
    body = {"rule_type": "keyword", "value": "dup"}

    assert (await client.post("/mute-rules", json=body, headers=headers)).status_code == 201
    resp = await client.post("/mute-rules", json=body, headers=headers)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_invalid_inputs_return_422(mute_api_setup: Setup):
    client, tokens, _ = mute_api_setup
    headers = {"Authorization": f"Bearer {tokens['alice']}"}

    # 非法 rule_type（Literal 校验）
    resp = await client.post("/mute-rules", json={"rule_type": "regex", "value": ".*"}, headers=headers)
    assert resp.status_code == 422
    # source 必须是数字
    resp = await client.post("/mute-rules", json={"rule_type": "source", "value": "abc"}, headers=headers)
    assert resp.status_code == 422
    # 空值
    resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": "   "}, headers=headers)
    assert resp.status_code == 422
    # keyword 超长
    resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": "x" * 101}, headers=headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_per_type_limit_returns_422(mute_api_setup: Setup):
    from app.services.mute_rule_service import MAX_RULES_PER_TYPE

    client, tokens, _ = mute_api_setup
    headers = {"Authorization": f"Bearer {tokens['alice']}"}
    for i in range(MAX_RULES_PER_TYPE):
        resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": f"kw-{i}"}, headers=headers)
        assert resp.status_code == 201
    resp = await client.post("/mute-rules", json={"rule_type": "keyword", "value": "overflow"}, headers=headers)
    assert resp.status_code == 422
    assert "50" in resp.json()["detail"]
