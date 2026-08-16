"""阅读记录 API 测试。

覆盖：
1. POST /read-records 首次上报创建记录
2. POST 幂等 upsert：同 target 多次上报累加 read_count/accumulated_ms，不插新行
3. POST depth 派生：累计达标后升级为 deep_read
4. GET /read-records 历史列表 + target_type 过滤
5. 用户隔离：不同用户记录互不可见

认证 mock 用 dependency_overrides[get_current_user] = lambda: User(id=...)。
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models.read_record  # noqa: F401
import app.models.user  # noqa: F401
from app.api.v1.auth import get_current_user
from app.api.v1.read_records import router as read_records_router
from app.core.database import Base, get_db
from app.models.user import User


@pytest_asyncio.fixture
async def read_records_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(read_records_router)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="reader@example.com", password_hash="hash")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await engine.dispose()


@pytest.mark.asyncio
async def test_report_creates_record_on_first_call(read_records_client):
    resp = await read_records_client.post(
        "/read-records",
        json={
            "target_type": "daily_report",
            "target_key": "2026-07-22",
            "target_id": 42,
            "duration_ms": 5000,
            "topic_keywords": ["AI", "新能源"],
            "category": "科技",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["read_count"] == 1
    assert body["accumulated_ms"] == 5000
    assert body["depth"] == "read"
    assert body["topic_keywords"] == ["AI", "新能源"]
    assert body["target_id"] == 42


@pytest.mark.asyncio
async def test_report_is_idempotent_and_accumulates(read_records_client):
    """核心语义：同 target 多次上报累加，不插新行。"""
    payload = {"target_type": "weekly_digest", "target_key": "2026-W29", "duration_ms": 3000}
    first = await read_records_client.post("/read-records", json=payload)
    second = await read_records_client.post("/read-records", json={**payload, "duration_ms": 7000})

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]  # 同一行
    assert second.json()["read_count"] == 2
    assert second.json()["accumulated_ms"] == 10000


@pytest.mark.asyncio
async def test_depth_upgrades_to_deep_read(read_records_client):
    """累计阅读次数 >=3 或时长 >=60s 升级为 deep_read。"""
    payload = {"target_type": "monthly_digest", "target_key": "2026-07", "duration_ms": 20000}
    for _ in range(3):
        resp = await read_records_client.post("/read-records", json=payload)
    assert resp.json()["read_count"] == 3
    assert resp.json()["depth"] == "deep_read"


@pytest.mark.asyncio
async def test_snapshot_first_read_is_pinned(read_records_client):
    """首读快照固化：后续上报的 topic_keywords 不覆盖已有快照。"""
    await read_records_client.post(
        "/read-records",
        json={"target_type": "daily_report", "target_key": "2026-07-22", "topic_keywords": ["首读关键词"]},
    )
    second = await read_records_client.post(
        "/read-records",
        json={
            "target_type": "daily_report",
            "target_key": "2026-07-22",
            "topic_keywords": ["不应覆盖"],
            "category": "财经",
        },
    )
    assert second.json()["topic_keywords"] == ["首读关键词"]
    # category 原为空，可回填
    assert second.json()["category"] == "财经"


@pytest.mark.asyncio
async def test_list_history_and_filter(read_records_client):
    await read_records_client.post("/read-records", json={"target_type": "daily_report", "target_key": "2026-07-21"})
    await read_records_client.post("/read-records", json={"target_type": "daily_report", "target_key": "2026-07-22"})
    await read_records_client.post("/read-records", json={"target_type": "weekly_digest", "target_key": "2026-W29"})

    all_resp = await read_records_client.get("/read-records")
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 3

    daily_resp = await read_records_client.get("/read-records?target_type=daily_report")
    assert daily_resp.json()["total"] == 2
    assert all(r["target_type"] == "daily_report" for r in daily_resp.json()["items"])


@pytest.mark.asyncio
async def test_user_isolation():
    """不同用户的阅读记录互不可见。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(read_records_router)

    async def override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="a@example.com", password_hash="h")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client_a:
        await client_a.post(
            "/read-records",
            json={"target_type": "daily_report", "target_key": "2026-07-22", "duration_ms": 1000},
        )
        resp_a = await client_a.get("/read-records")
        assert resp_a.json()["total"] == 1

    # 切换为用户 2
    app.dependency_overrides[get_current_user] = lambda: User(id=2, email="b@example.com", password_hash="h")
    async with AsyncClient(transport=transport, base_url="http://testserver") as client_b:
        resp_b = await client_b.get("/read-records")
        assert resp_b.json()["total"] == 0  # 看不到用户 1 的记录

    await engine.dispose()
