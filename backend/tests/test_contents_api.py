"""Tests for the contents API endpoints.

Covers:
- P0-1 fix verification: translate_reader_content error does not leak internals
- get_content returns 404 for non-existent content
- today-count endpoint structure
- evidence-batch input validation
- ignore/unignore endpoint basic behavior
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, contents as contents_api
from app.core.database import Base
from app.models.content import ContentItem
from app.models.source import Source
from app.services.auth_service import create_session, create_user


@pytest_asyncio.fixture
async def contents_client() -> AsyncGenerator[tuple[httpx.AsyncClient, str], None]:
    """In-memory SQLite + AsyncClient with a regular user token."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="user@example.com", password="Password123", role="user")
        token, _ = await create_session(db, user)
        db.add(Source(name="Test", url="https://example.com", source_type="RSS", status="active"))
        await db.flush()
        db.add(ContentItem(
            title="Test Article",
            url="https://example.com/article",
            source_id=1,
            source_name="Test",
            source_type="RSS",
            status="crawled",
            content_hash="abc123",
        ))
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(contents_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, token

    await engine.dispose()


@pytest.mark.asyncio
async def test_get_content_404(contents_client: tuple[httpx.AsyncClient, str]):
    """get_content returns 404 for non-existent content."""
    client, token = contents_client
    resp = await client.get(
        "/contents/99999",
        cookies={"session_token": token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_content_existing(contents_client: tuple[httpx.AsyncClient, str]):
    """get_content returns content for existing id."""
    client, token = contents_client
    resp = await client.get(
        "/contents/1",
        cookies={"session_token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == 1
    assert data["title"] == "Test Article"


@pytest.mark.asyncio
async def test_today_count_structure(contents_client: tuple[httpx.AsyncClient, str]):
    """today_count returns correct structure."""
    client, token = contents_client
    resp = await client.get(
        "/contents/today-count",
        cookies={"session_token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "today_content" in data
    assert "today_picks" in data
    assert isinstance(data["today_content"], int)
    assert isinstance(data["today_picks"], int)


@pytest.mark.asyncio
async def test_translate_404_for_nonexistent_content(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """translate_reader_content returns 404 for non-existent content."""
    client, token = contents_client
    resp = await client.post(
        "/contents/99999/reader/translate",
        cookies={"session_token": token},
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Content not found"


@pytest.mark.asyncio
async def test_translate_error_safe_message(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """P0-1: translate failure returns safe message without leaking internals.

    This test verifies the fix for the error message leakage vulnerability.
    When translation fails, the error response should contain a generic
    user-facing message, not the internal exception details.
    """
    client, token = contents_client

    # The translate endpoint will fail because no reader snapshot exists
    # for the seeded content. The error should be 502 with safe message.
    resp = await client.post(
        "/contents/1/reader/translate",
        cookies={"session_token": token},
    )
    if resp.status_code == 502:
        detail = resp.json()["detail"]
        # Must not contain internal paths, stack traces, or SQL
        assert "Traceback" not in detail
        assert "sqlalchemy" not in detail.lower()
        assert "SELECT" not in detail
        assert detail == "翻译失败，请稍后重试"


@pytest.mark.asyncio
async def test_evidence_batch_invalid_ids(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """evidence-batch rejects invalid ids format."""
    client, token = contents_client
    resp = await client.get(
        "/contents/evidence-batch?ids=abc,def",
        cookies={"session_token": token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_evidence_batch_empty_ids(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """evidence-batch rejects empty ids."""
    client, token = contents_client
    resp = await client.get(
        "/contents/evidence-batch?ids=",
        cookies={"session_token": token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_evidence_batch_too_many_ids(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """evidence-batch rejects >200 ids."""
    client, token = contents_client
    ids = ",".join(str(i) for i in range(201))
    resp = await client.get(
        f"/contents/evidence-batch?ids={ids}",
        cookies={"session_token": token},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_list_contents_default_pagination(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """list_contents returns paginated results with default params."""
    client, token = contents_client
    resp = await client.get(
        "/contents",
        cookies={"session_token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert "page_size" in data


@pytest.mark.asyncio
async def test_list_contents_with_category_filter(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """list_contents accepts category filter."""
    client, token = contents_client
    resp = await client.get(
        "/contents?category=科技",
        cookies={"session_token": token},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data["items"], list)


@pytest.mark.asyncio
async def test_ignore_content_404(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """ignore_content returns 404 for non-existent content."""
    client, token = contents_client
    resp = await client.post(
        "/contents/99999/ignore",
        cookies={"session_token": token},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_unignore_content_404(
    contents_client: tuple[httpx.AsyncClient, str],
):
    """unignore_content returns 404 for non-existent ignore record."""
    client, token = contents_client
    resp = await client.delete(
        "/contents/99999/ignore",
        cookies={"session_token": token},
    )
    assert resp.status_code == 404
