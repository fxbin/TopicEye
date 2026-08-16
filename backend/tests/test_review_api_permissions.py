from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import (
    auth as auth_api,
    daily_reports as daily_reports_api,
    monthly_digests as monthly_digests_api,
    weekly_digests as weekly_digests_api,
)
from app.core.database import Base
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_review_read_apis_require_login():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="review-user@example.com", password="Password123", role="user")
        token, _session = await create_session(db, user)
        await db.commit()

    app = FastAPI()
    app.include_router(daily_reports_api.router)
    app.include_router(weekly_digests_api.router)
    app.include_router(monthly_digests_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    for dependency in {
        auth_api.get_db,
        daily_reports_api.get_db,
        weekly_digests_api.get_db,
        monthly_digests_api.get_db,
    }:
        app.dependency_overrides[dependency] = override_get_db

    endpoints = [
        "/daily-reports?limit=1",
        "/weekly-digests?limit=1",
        "/monthly-digests?limit=1",
    ]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for endpoint in endpoints:
            anonymous = await client.get(endpoint)
            assert anonymous.status_code == 401, endpoint

            authorized = await client.get(endpoint, headers={"Authorization": f"Bearer {token}"})
            assert authorized.status_code == 200, endpoint
            assert authorized.json()["items"] == []

    await engine.dispose()
