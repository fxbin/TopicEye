from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api
from app.api.v1 import mother_topics as mother_topics_api
from app.core.database import Base
from app.models.mother_topic import MotherTopic
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_mother_topics_user_and_admin_boundaries():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="mother-user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="mother-admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        db.add_all(
            [
                MotherTopic(name="AI 工具", keywords=["AI", "效率"], is_active=True, display_order=1),
                MotherTopic(name="停用母题", keywords=["旧"], is_active=False, display_order=2),
            ]
        )
        await db.commit()

    app = FastAPI()
    app.include_router(mother_topics_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[mother_topics_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.get("/mother-topics?active_only=true")
        assert anonymous.status_code == 401

        user_active = await client.get(
            "/mother-topics?active_only=true",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_active.status_code == 200
        assert [item["name"] for item in user_active.json()] == ["AI 工具"]

        user_full = await client.get(
            "/mother-topics?active_only=false",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_full.status_code == 403

        admin_full = await client.get(
            "/mother-topics?active_only=false",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_full.status_code == 200
        assert [item["name"] for item in admin_full.json()] == ["AI 工具", "停用母题"]

        user_score = await client.post(
            "/mother-topics/score-batch",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"items": [{"title": "AI 效率工具观察", "summary": "提升创作效率"}]},
        )
        assert user_score.status_code == 200
        assert user_score.json()["results"][0]["top_topic"] == "AI 工具"

        user_create = await client.post(
            "/mother-topics",
            headers={"Authorization": f"Bearer {user_token}"},
            json={"name": "用户不可创建", "keywords": ["test"]},
        )
        assert user_create.status_code == 403

        admin_create = await client.post(
            "/mother-topics",
            headers={"Authorization": f"Bearer {admin_token}"},
            json={"name": "管理员创建", "keywords": ["admin"], "display_order": 3},
        )
        assert admin_create.status_code == 200
        assert admin_create.json()["name"] == "管理员创建"

    await engine.dispose()
