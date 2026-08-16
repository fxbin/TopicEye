from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, trending as trending_api, trends as trends_api
from app.core.database import Base
from app.models.trending import TrendingCategory, TrendingItem, TrendingSource
from app.services import trending_snapshot
from app.services.auth_service import create_session, create_user


class _FakeTrendSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def commit(self):
        return None


def _fake_trend_session_factory():
    return _FakeTrendSession()


@pytest.mark.asyncio
async def test_trending_write_apis_require_admin_and_keep_sync_all_route(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="trend-user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="trend-admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        await db.commit()

    calls: list[str] = []

    async def fake_sync_source(source_name: str, db: AsyncSession):
        calls.append(f"source:{source_name}")
        return {"fetched": 3}

    async def fake_sync_all(db: AsyncSession):
        calls.append("all")
        return {"weibo": {"fetched": 3}}

    async def fake_save_all_snapshots(db: AsyncSession):
        calls.append("save_snapshots")
        return {"weibo": 3}

    async def fake_snapshot_daily_trends(db, target_date=None):
        calls.append("trend_snapshot")
        return {"topics": 1, "keywords": 2, "date": "2026-06-05"}

    monkeypatch.setattr(trending_api, "sync_trending_source", fake_sync_source)
    monkeypatch.setattr(trending_api, "sync_all_trending", fake_sync_all)
    monkeypatch.setattr(trending_snapshot, "save_all_snapshots", fake_save_all_snapshots)
    monkeypatch.setattr(trends_api, "snapshot_daily_trends", fake_snapshot_daily_trends)
    monkeypatch.setattr(trends_api, "async_session", _fake_trend_session_factory)

    app = FastAPI()
    app.include_router(trending_api.router)
    app.include_router(trends_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[trending_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        for endpoint in [
            "/trending/sync/weibo",
            "/trending/sync-all",
            "/trending/snapshots/save",
            "/trends/snapshot",
        ]:
            anonymous = await client.post(endpoint)
            assert anonymous.status_code == 401, endpoint

            ordinary = await client.post(endpoint, headers={"Authorization": f"Bearer {user_token}"})
            assert ordinary.status_code == 403, endpoint

        sync_all = await client.post("/trending/sync-all", headers={"Authorization": f"Bearer {admin_token}"})
        assert sync_all.status_code == 200
        assert sync_all.json() == {"weibo": {"fetched": 3}}

        sync_one = await client.post("/trending/sync/weibo", headers={"Authorization": f"Bearer {admin_token}"})
        assert sync_one.status_code == 200
        assert sync_one.json() == {"fetched": 3}

        saved = await client.post("/trending/snapshots/save", headers={"Authorization": f"Bearer {admin_token}"})
        assert saved.status_code == 200
        assert saved.json() == {"saved": {"weibo": 3}}

        trend_snapshot = await client.post("/trends/snapshot", headers={"Authorization": f"Bearer {admin_token}"})
        assert trend_snapshot.status_code == 200
        assert trend_snapshot.json() == {
            "status": "ok",
            "topics": 1,
            "keywords": 2,
            "date": "2026-06-05",
        }

    assert calls == ["all", "source:weibo", "save_snapshots", "trend_snapshot"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_trending_angle_generation_requires_login_not_admin(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="angle-user@example.com", password="Password123", role="user")
        token, _ = await create_session(db, user)
        db.add(
            TrendingItem(
                id=1,
                source=TrendingSource.WEIBO,
                category=TrendingCategory.HOT,
                rank=1,
                title="AI 角度测试话题",
                url="https://example.com/angle",
                hot_value=100,
                hot_value_raw="100",
                extra={"keywords": ["AI"]},
                batch_id="angle-test",
            )
        )
        await db.commit()

    async def fake_generate_angles_for_topic(topic: str, keywords: list[str], platform_titles: list[str]):
        return {
            "common_angles": ["常规角度"],
            "contrast_angles": [{"angle": "反差角度", "reasoning": "有解释力"}],
            "angle_note": f"{topic}:{','.join(keywords)}:{platform_titles[0]}",
        }

    import app.services.angle_recommend as angle_recommend

    monkeypatch.setattr(angle_recommend, "generate_angles_for_topic", fake_generate_angles_for_topic)

    app = FastAPI()
    app.include_router(trending_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[trending_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.get("/trending/angles?topic=AI%20角度测试")
        assert anonymous.status_code == 401

        authorized = await client.get(
            "/trending/angles?topic=AI%20角度测试",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert authorized.status_code == 200
        assert authorized.json()["contrast_angles"][0]["angle"] == "反差角度"

    await engine.dispose()
