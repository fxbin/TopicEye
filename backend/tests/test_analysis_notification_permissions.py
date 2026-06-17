from __future__ import annotations

from datetime import datetime, timezone, UTC
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import analyses as analyses_api
from app.api.v1 import auth as auth_api
from app.api.v1 import notifications as notifications_api
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.notification import Notification
from app.services import notification_service
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_analysis_and_notifications_require_login(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="analysis-user@example.com", password="Password123", role="user")
        token, _ = await create_session(db, user)
        db.add(
            ContentItem(
                id=1,
                title="分析权限样本",
                url="https://example.com/analysis-permission",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.PENDING,
                crawled_at=datetime.now(UTC),
            )
        )
        db.add(
            AiAnalysis(
                id=1,
                content_id=1,
                summary="已有分析",
                curation_score=66,
            )
        )
        db.add(
            Notification(
                id=1,
                type="info",
                category="system",
                title="登录通知",
                message="仅登录可见",
                is_read=False,
            )
        )
        await db.commit()

    monkeypatch.setattr(notification_service, "async_session", session_factory)

    async def fake_analyze_batch_concurrent(content_ids: list[int], **_kwargs):
        return []

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fake_analyze_batch_concurrent)

    app = FastAPI()
    app.include_router(analyses_api.router)
    app.include_router(notifications_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[analyses_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous_analysis = await client.get("/analyses/content/1")
        assert anonymous_analysis.status_code == 401

        authorized_analysis = await client.get(
            "/analyses/content/1",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authorized_analysis.status_code == 200
        assert authorized_analysis.json()["summary"] == "已有分析"

        anonymous_pending = await client.post("/analyses/pending?limit=1")
        assert anonymous_pending.status_code == 401

        authorized_pending = await client.post(
            "/analyses/pending?limit=1&sync=true",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authorized_pending.status_code == 200

        anonymous_notifications = await client.get("/notifications/unread-count")
        assert anonymous_notifications.status_code == 401

        authorized_notifications = await client.get(
            "/notifications/unread-count",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authorized_notifications.status_code == 200
        assert authorized_notifications.json() == {"count": 1}

        marked = await client.post(
            "/notifications/1/read",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert marked.status_code == 200
        assert marked.json() == {"success": True}

    await engine.dispose()
