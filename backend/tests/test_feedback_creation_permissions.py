from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, creation as creation_api, feedback as feedback_api
from app.api.v1 import _db_write as db_write_api
from app.core.database import Base
from app.models.content import ContentItem, ContentStatus
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_feedback_and_creation_mutation_apis_require_login(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="workflow-user@example.com", password="Password123", role="user")
        second_user = await create_user(db, email="workflow-user-2@example.com", password="Password123", role="user")
        token, _session = await create_session(db, user)
        second_token, _second_session = await create_session(db, second_user)
        db.add(
            ContentItem(
                id=1,
                title="创作与反馈样本",
                url="https://example.com/workflow",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()

    async def fake_generate_creation_plan(db, content_id: int, platform: str, user_id: int | None = None):
        return {"titles": ["测试方案"], "_meta": {"content_id": content_id, "platform": platform}}

    monkeypatch.setattr(creation_api, "generate_creation_plan", fake_generate_creation_plan)

    app = FastAPI()
    app.include_router(feedback_api.router)
    app.include_router(creation_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    # creation.py 不用 Depends(get_db) 而是内联 async_session(),
    # 因此没有 module-level get_db 可被 override。只 override 真正存在的。
    for dependency in {
        auth_api.get_db,
        feedback_api.get_db,
    }:
        app.dependency_overrides[dependency] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # /creation/platforms 在 creation router 下,整 router 挂了
        # Depends(get_current_user),所以也要带 token 才能访问
        platforms = await client.get(
            "/creation/platforms",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert platforms.status_code == 200

        anonymous_feedback = await client.post(
            "/feedback",
            json={"content_id": 1, "feedback_type": "great_pick"},
        )
        assert anonymous_feedback.status_code == 401

        authorized_feedback = await client.post(
            "/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={"content_id": 1, "feedback_type": "great_pick"},
        )
        assert authorized_feedback.status_code == 201
        assert authorized_feedback.json()["user_id"] == user.id

        second_feedback = await client.post(
            "/feedback",
            headers={"Authorization": f"Bearer {second_token}"},
            json={"content_id": 1, "feedback_type": "like"},
        )
        assert second_feedback.status_code == 201
        assert second_feedback.json()["user_id"] == second_user.id
        assert second_feedback.json()["id"] != authorized_feedback.json()["id"]

        own_feedback = await client.get(
            "/feedback/content/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert own_feedback.status_code == 200
        assert [item["user_id"] for item in own_feedback.json()] == [user.id]

        anonymous_stats = await client.get("/feedback/stats")
        assert anonymous_stats.status_code == 401

        authorized_stats = await client.get("/feedback/stats", headers={"Authorization": f"Bearer {token}"})
        assert authorized_stats.status_code == 200
        assert authorized_stats.json()["total"] == 2

        anonymous_plan = await client.post(
            "/creation/plan",
            json={"content_id": 1, "platform": "wechat"},
        )
        assert anonymous_plan.status_code == 401

        authorized_plan = await client.post(
            "/creation/plan",
            headers={"Authorization": f"Bearer {token}"},
            json={"content_id": 1, "platform": "wechat"},
        )
        assert authorized_plan.status_code == 200
        assert authorized_plan.json()["titles"] == ["测试方案"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_feedback_submit_uses_sqlite_lock_retry(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="feedback-retry@example.com", password="Password123", role="user")
        token, _session = await create_session(db, user)
        db.add(
            ContentItem(
                id=1,
                title="反馈重试样本",
                url="https://example.com/feedback-retry",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()

    retry_calls = 0

    async def retry_spy(operation, **kwargs):
        nonlocal retry_calls
        retry_calls += 1
        assert kwargs["attempts"] == 3
        assert kwargs["base_delay"] == 0.1
        assert kwargs["on_retry"] is not None
        return await operation()

    monkeypatch.setattr(db_write_api, "retry_sqlite_locked", retry_spy)

    app = FastAPI()
    app.include_router(feedback_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[feedback_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/feedback",
            headers={"Authorization": f"Bearer {token}"},
            json={"content_id": 1, "feedback_type": "great_pick"},
        )
        assert response.status_code == 201

    assert retry_calls == 1
    await engine.dispose()
