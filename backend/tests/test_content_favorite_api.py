from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1.auth import get_current_user
from app.api.v1 import contents as contents_api
from app.api.v1 import favorites as favorites_api
from app.core.database import Base
from app.core.dependencies import get_db
from app.models.content import ContentItem, ContentStatus
from app.models.user import User
from app.services.favorite_cache import invalidate_favorite_cache


@pytest_asyncio.fixture
async def contents_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    invalidate_favorite_cache()

    app = FastAPI()
    app.include_router(contents_api.router)
    app.include_router(favorites_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[contents_api.get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: User(id=1, email="user@example.com", password_hash="hash")

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="收藏联动样本",
                url="https://example.com/content-favorite",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    invalidate_favorite_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_content_favorite_toggle_returns_favorite_id_and_state(contents_client: httpx.AsyncClient):
    created = await contents_client.post("/contents/1/favorite")
    assert created.status_code == 200
    created_payload = created.json()
    assert created_payload["is_favorited"] is True
    assert isinstance(created_payload["favorite_id"], int)

    state = await contents_client.get("/favorites/state?target_type=content&target_ids=1")
    assert state.status_code == 200
    assert state.json()["items"] == [
        {
            "target_key": "1",
            "is_favorited": True,
            "favorite_id": created_payload["favorite_id"],
        }
    ]

    removed = await contents_client.post("/contents/1/favorite")
    assert removed.status_code == 200
    assert removed.json() == {"is_favorited": False, "favorite_id": None}
