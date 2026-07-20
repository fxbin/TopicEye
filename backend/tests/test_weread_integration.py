from __future__ import annotations

from datetime import datetime, timezone, UTC
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1.auth import router as auth_router
from app.api.v1.integrations import (
    delete_weread_integration,
    get_weread_integration,
    router as integrations_router,
    sync_weread,
    update_weread_integration,
)
from app.core.config import DEFAULT_LOCAL_SECRET_KEY, settings
from app.core.database import Base
from app.core.database import get_db
from app.models.content import ContentItem
from app.models.source import Source, SourceStatus
from app.models.user_integration import UserIntegration
from app.schemas.integration import IntegrationUpdateRequest
from app.services.auth_service import create_user
from app.services.integration_service import WEREAD_PROVIDER, WEREAD_INSTALL_COMMAND, get_user_integration
from app.services.secret_store import decrypt_secret, encrypt_secret, is_encrypted_secret
from app.services.source_cache import (
    default_source_list_cache_params,
    get_cached_source_list,
    invalidate_source_list_cache,
    set_cached_source_list,
)
import app.services.weread_materials as weread_materials
from app.services.weread_materials import normalize_weread_entries, redact_weread_sync_error


def test_production_runtime_rejects_default_secret(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "production")
    monkeypatch.setattr(settings, "APP_SECRET_KEY", DEFAULT_LOCAL_SECRET_KEY)
    monkeypatch.setattr(settings, "INTEGRATION_SECRET_KEY", None)

    with pytest.raises(RuntimeError, match="APP_ENV=production requires"):
        app.main.ensure_runtime_secret_safety()

    with pytest.raises(RuntimeError, match="Production secret encryption requires"):
        encrypt_secret("wr_secret_1234567890")


@pytest_asyncio.fixture
async def weread_http_client(monkeypatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(integrations_router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_status_masks_api_key_and_reports_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", None)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="weread@example.com", password="Password123")
        status = await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_1234567890"),
            user,
            db,
        )

        assert status["configured"] is True
        assert status["api_key_hint"] == "wr_s...7890"
        assert "wr_secret_1234567890" not in str(status)
        assert status["sync_endpoint_configured"] is True
        assert status["install_command"] == WEREAD_INSTALL_COMMAND
        stored = await get_user_integration(db, user_id=user.id, provider=WEREAD_PROVIDER)
        assert stored is not None
        assert is_encrypted_secret(stored.api_key)
        assert "wr_secret_1234567890" not in stored.api_key
        assert decrypt_secret(stored.api_key) == "wr_secret_1234567890"

        fetched = await get_weread_integration(user, db)
        assert fetched["api_key_hint"] == "wr_s...7890"
        assert "wr_secret_1234567890" not in str(fetched)

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_integration_reads_legacy_plaintext_key(monkeypatch):
    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", None)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="legacy-weread@example.com", password="Password123")
        db.add(
            UserIntegration(
                user_id=user.id,
                provider=WEREAD_PROVIDER,
                api_key="wr_secret_legacy_123456",
                config={},
            )
        )
        await db.flush()

        status = await get_weread_integration(user, db)

        assert status["configured"] is True
        assert status["api_key_hint"] == "wr_s...3456"
        assert "wr_secret_legacy_123456" not in str(status)

    await engine.dispose()


def test_weread_api_key_rejects_blank_after_strip():
    with pytest.raises(ValueError):
        IntegrationUpdateRequest(api_key="        ")


def test_weread_sync_error_redacts_api_key_and_bearer_token():
    message = (
        "Skill failed for Authorization: Bearer wr_secret red/123; "
        "query_key=wr_secret%20red%2F123 raw=wr_secret red/123"
    )

    redacted = redact_weread_sync_error(message, "wr_secret red/123")

    assert "wr_secret red/123" not in redacted
    assert "wr_secret%20red%2F123" not in redacted
    assert "Bearer ***" in redacted
    assert redacted.count("***") >= 2


@pytest.mark.asyncio
async def test_weread_fetch_http_error_uses_redacted_response_body(monkeypatch):
    api_key = "wr_secret_http_error_123456"

    class FakeResponse:
        status_code = 500
        text = "Gateway rejected Authorization: Bearer wr_secret_http_error_123456"

        def raise_for_status(self):
            request = httpx.Request("POST", "https://i.weread.qq.com/api/agent/gateway")
            response = httpx.Response(self.status_code, request=request, text=self.text)
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        def json(self):
            return {}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            assert url == weread_materials.WEREAD_GATEWAY_URL
            assert headers["Authorization"] == f"Bearer {api_key}"
            assert json["api_name"] == "/user/notebooks"
            return FakeResponse()

    monkeypatch.setattr(weread_materials.httpx, "Client", FakeClient)

    with pytest.raises(RuntimeError) as error:
        await weread_materials.fetch_weread_materials(api_key, limit=1)

    assert "微信读书接口返回 500" in str(error.value)
    assert api_key not in str(error.value)
    assert "Bearer ***" in str(error.value)


@pytest.mark.asyncio
async def test_weread_fetch_full_sync_paginates_until_no_more(monkeypatch):
    """limit=0（全量同步）时持续翻页直到 hasMore != 1。"""
    call_count = {"n": 0}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            assert url == weread_materials.WEREAD_GATEWAY_URL
            call_count["n"] += 1
            if call_count["n"] == 1:
                return FakeResponse({
                    "books": [
                        {"title": f"书{i}", "sort": i, "bookId": f"b{i}"}
                        for i in range(1, 4)
                    ],
                    "hasMore": 1,
                })
            return FakeResponse({
                "books": [
                    {"title": f"书{i}", "sort": i, "bookId": f"b{i}"}
                    for i in range(4, 6)
                ],
                "hasMore": 0,
            })

    monkeypatch.setattr(weread_materials.httpx, "Client", FakeClient)

    entries = await weread_materials.fetch_weread_materials("wr_test_key_123456", limit=0)

    assert call_count["n"] == 2
    assert len(entries) == 5
    assert [e["title"] for e in entries] == ["书1", "书2", "书3", "书4", "书5"]


@pytest.mark.asyncio
async def test_weread_fetch_limit_caps_total_entries(monkeypatch):
    """limit > 0 时截断到指定条数。"""
    call_count = {"n": 0}

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200
            self.text = ""

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, *, headers, json):
            call_count["n"] += 1
            n = call_count["n"]
            return FakeResponse({
                "books": [
                    {"title": f"页{n}-{i}", "sort": n * 10 + i, "bookId": f"b{n}-{i}"}
                    for i in range(3)
                ],
                "hasMore": 1,
            })

    monkeypatch.setattr(weread_materials.httpx, "Client", FakeClient)

    entries = await weread_materials.fetch_weread_materials("wr_test_key_123456", limit=5)

    assert len(entries) == 5
    assert call_count["n"] == 2


@pytest.mark.asyncio
async def test_weread_integration_delete_clears_configuration(monkeypatch):
    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", "http://127.0.0.1:9999/weread")
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="delete-weread@example.com", password="Password123")
        configured = await update_weread_integration(
            IntegrationUpdateRequest(api_key="  wr_secret_delete_123456  ", config={"tag": "inbox"}),
            user,
            db,
        )
        assert configured["configured"] is True
        assert configured["api_key_hint"] == "wr_s...3456"
        assert configured["config"] == {"tag": "inbox"}

        integration = await get_user_integration(db, user_id=user.id, provider="weread")
        assert integration is not None
        integration.last_sync_at = user.created_at
        integration.last_sync_status = "error"
        integration.last_sync_error = "旧同步错误"
        await db.flush()

        deleted = await delete_weread_integration(user, db)
        assert deleted["configured"] is False
        assert deleted["api_key_hint"] is None
        assert deleted["config"] == {}
        assert deleted["last_sync_at"] is None
        assert deleted["last_sync_status"] is None
        assert deleted["last_sync_error"] is None

        fetched = await get_weread_integration(user, db)
        assert fetched["configured"] is False
        assert fetched["api_key_hint"] is None
        assert fetched["last_sync_status"] is None
        assert fetched["last_sync_error"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_integration_is_scoped_to_current_user(monkeypatch):
    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", None)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        owner = await create_user(db, email="owner-weread@example.com", password="Password123")
        other = await create_user(db, email="other-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_owner_123456"),
            owner,
            db,
        )

        owner_status = await get_weread_integration(owner, db)
        other_status = await get_weread_integration(other, db)

        assert owner_status["configured"] is True
        assert owner_status["api_key_hint"] == "wr_s...3456"
        assert other_status["configured"] is False
        assert other_status["api_key_hint"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_sync_gateway_error_persists_and_key_change_resets(monkeypatch):
    """同步失败时错误状态持久化；换 Key 后状态重置。"""
    async def failed_sync(db, integration, *, user_id, api_key, limit=0):
        raise RuntimeError("无法连接微信读书服务: connection refused")

    monkeypatch.setattr("app.api.v1.integrations.sync_weread_materials", failed_sync)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="sync-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_1234567890"),
            user,
            db,
        )

        error = None
        try:
            await sync_weread(limit=50, current_user=user, db=db)
        except HTTPException as exc:
            error = exc

        assert error is not None
        assert error.status_code == 502
        assert "无法连接微信读书服务" in str(error.detail)

        status = await get_weread_integration(user, db)
        assert status["last_sync_status"] == "error"
        assert "无法连接微信读书服务" in status["last_sync_error"]

        refreshed = await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_replaced_123456"),
            user,
            db,
        )
        assert refreshed["configured"] is True
        assert refreshed["last_sync_at"] is None
        assert refreshed["last_sync_status"] is None
        assert refreshed["last_sync_error"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_sync_rejects_active_user_lease(monkeypatch):
    async def fail_fetch(api_key: str, *, limit: int = 0):
        raise AssertionError("active weread sync lease should skip remote fetch")

    monkeypatch.setattr(weread_materials, "fetch_weread_materials", fail_fetch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="sync-active-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_active_123456"),
            user,
            db,
        )
        integration = await get_user_integration(db, user_id=user.id, provider=WEREAD_PROVIDER)
        assert integration is not None
        integration.last_sync_at = datetime.now(UTC)
        integration.last_sync_status = "syncing"
        integration.last_sync_error = None
        await db.flush()

        error = None
        try:
            await sync_weread(limit=1, current_user=user, db=db)
        except HTTPException as exc:
            error = exc

        assert error is not None
        assert error.status_code == 409
        assert "正在同步" in str(error.detail)

        status = await get_weread_integration(user, db)
        assert status["last_sync_status"] == "syncing"
        assert status["last_sync_error"] is None

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_sync_error_state_persists_and_key_changes_reset_over_http(
    weread_http_client: httpx.AsyncClient,
    monkeypatch,
):
    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", None)

    # mock gateway 直连失败（不再依赖 endpoint 配置）
    async def failing_fetch(api_key, *, limit=0):
        raise RuntimeError("无法连接微信读书服务: connection refused")

    monkeypatch.setattr("app.services.weread_materials.fetch_weread_materials", failing_fetch)

    registered = await weread_http_client.post(
        "/auth/register",
        json={
            "email": "weread-http@example.com",
            "password": "Password123",
            "display_name": "WeRead HTTP",
        },
    )
    assert registered.status_code == 201
    token = registered.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    configured = await weread_http_client.put(
        "/integrations/weread",
        headers=headers,
        json={"api_key": "wr_secret_http_123456", "config": {}},
    )
    assert configured.status_code == 200
    assert configured.json()["configured"] is True

    failed = await weread_http_client.post("/integrations/weread/sync?limit=1", headers=headers)
    assert failed.status_code == 502
    assert "无法连接微信读书服务" in failed.json()["detail"]

    errored = await weread_http_client.get("/integrations/weread", headers=headers)
    assert errored.status_code == 200
    assert errored.json()["last_sync_status"] == "error"
    assert "无法连接微信读书服务" in errored.json()["last_sync_error"]

    replaced = await weread_http_client.put(
        "/integrations/weread",
        headers=headers,
        json={"api_key": "wr_secret_http_replaced_123456", "config": {}},
    )
    assert replaced.status_code == 200
    assert replaced.json()["configured"] is True
    assert replaced.json()["last_sync_at"] is None
    assert replaced.json()["last_sync_status"] is None
    assert replaced.json()["last_sync_error"] is None

    cleared = await weread_http_client.delete("/integrations/weread", headers=headers)
    assert cleared.status_code == 200
    assert cleared.json()["configured"] is False
    assert cleared.json()["api_key_hint"] is None
    assert cleared.json()["last_sync_status"] is None
    assert cleared.json()["last_sync_error"] is None


@pytest.mark.asyncio
async def test_weread_sync_failure_persists_redacted_error(monkeypatch):
    async def failed_fetch(api_key: str, *, limit: int = 0):
        assert api_key == "wr_secret_leaky_123456"
        raise RuntimeError("Skill rejected Authorization: Bearer wr_secret_leaky_123456 token=wr_secret_leaky_123456")

    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", "http://127.0.0.1:9999/weread")
    monkeypatch.setattr(weread_materials, "fetch_weread_materials", failed_fetch)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="sync-redacted-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_leaky_123456"),
            user,
            db,
        )

        error = None
        try:
            await sync_weread(limit=1, current_user=user, db=db)
        except HTTPException as exc:
            error = exc

        assert error is not None
        assert error.status_code == 502
        assert "wr_secret_leaky_123456" not in str(error.detail)
        assert "Bearer ***" in str(error.detail)

        status = await get_weread_integration(user, db)
        assert status["last_sync_status"] == "error"
        assert "wr_secret_leaky_123456" not in status["last_sync_error"]
        assert "Bearer ***" in status["last_sync_error"]

        source = await db.scalar(select(Source).where(Source.name == "微信读书素材"))
        assert source is not None
        assert source.status == SourceStatus.ERROR
        assert "wr_secret_leaky_123456" not in source.sync_error
        assert "Bearer ***" in source.sync_error

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_sync_unknown_error_is_redacted_at_api_boundary(monkeypatch):
    async def failed_sync(db, integration, *, user_id: int, api_key: str, limit: int = 0):
        assert api_key == "wr_secret_boundary_123456"
        raise ValueError("raw failure Authorization: Bearer wr_secret_boundary_123456 token=wr_secret_boundary_123456")

    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", "http://127.0.0.1:9999/weread")
    monkeypatch.setattr("app.api.v1.integrations.sync_weread_materials", failed_sync)
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="sync-boundary-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key="wr_secret_boundary_123456"),
            user,
            db,
        )

        error = None
        try:
            await sync_weread(limit=1, current_user=user, db=db)
        except HTTPException as exc:
            error = exc

        assert error is not None
        assert error.status_code == 502
        assert "wr_secret_boundary_123456" not in str(error.detail)
        assert "Bearer ***" in str(error.detail)
        assert "微信读书素材同步失败" in str(error.detail)

    await engine.dispose()


@pytest.mark.asyncio
async def test_weread_sync_imports_materials_and_deduplicates(monkeypatch):
    async def fake_fetch(api_key: str, *, limit: int = 0):
        assert api_key == "wr_secret_sync_123456"
        assert limit == 2
        return [
            {
                "title": "微信读书选题一",
                "url": "https://weread.qq.com/note/1",
                "author": "作者一",
                "summary": "第一条阅读笔记。",
                "raw_content": "第一条阅读笔记。",
            },
            {
                "title": "微信读书选题二",
                "url": "https://weread.qq.com/note/2",
                "author": "作者二",
                "summary": "第二条阅读笔记。",
                "raw_content": "第二条阅读笔记。",
            },
        ]

    monkeypatch.setattr(settings, "WEREAD_SKILL_API_URL", "http://127.0.0.1:9999/weread")
    monkeypatch.setattr(weread_materials, "fetch_weread_materials", fake_fetch)
    post_sync_requests = []
    monkeypatch.setattr(
        "app._post_sync_pipeline._request_post_sync_pipeline",
        lambda stats: post_sync_requests.append(stats) or True,
    )
    invalidate_source_list_cache()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="sync-success-weread@example.com", password="Password123")
        await update_weread_integration(
            IntegrationUpdateRequest(api_key=" wr_secret_sync_123456 "),
            user,
            db,
        )
        integration = await get_user_integration(db, user_id=user.id, provider=WEREAD_PROVIDER)
        assert integration is not None
        assert is_encrypted_secret(integration.api_key)
        assert "wr_secret_sync_123456" not in integration.api_key

        source_cache_params = default_source_list_cache_params()
        set_cached_source_list(source_cache_params, {"items": [{"name": "旧信源缓存"}], "total": 1})
        assert get_cached_source_list(source_cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS) is not None

        first = await sync_weread(limit=2, current_user=user, db=db)
        assert first.fetched == 2
        assert first.new == 2
        assert first.duplicates == 0
        assert first.source_name == "微信读书素材"
        assert post_sync_requests == [{"new": 2}]
        assert get_cached_source_list(source_cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS) is None

        source = await db.scalar(select(Source).where(Source.name == "微信读书素材"))
        assert source is not None
        assert source.status == SourceStatus.ACTIVE
        assert source.sync_error is None

        rows = (
            (
                await db.execute(
                    select(ContentItem).where(ContentItem.source_id == source.id).order_by(ContentItem.title.asc())
                )
            )
            .scalars()
            .all()
        )
        assert [item.title for item in rows] == ["微信读书选题一", "微信读书选题二"]
        assert {item.platform for item in rows} == {"微信读书"}
        assert {item.category for item in rows} == {"阅读素材"}

        second = await sync_weread(limit=2, current_user=user, db=db)
        assert second.fetched == 2
        assert second.new == 0
        assert second.duplicates == 2
        assert post_sync_requests == [{"new": 2}]

        status = await get_weread_integration(user, db)
        assert status["last_sync_status"] == "success"
        assert status["last_sync_error"] is None

    invalidate_source_list_cache()
    await engine.dispose()


def test_normalize_weread_entries_accepts_books_notes_and_highlights():
    payload = {
        "books": [
            {
                "title": "系统之美",
                "author": "德内拉",
                "coverUrl": "https://img.example.com/book.jpg",
                "bookUrl": "https://weread.qq.com/book-detail",
                "summary": "复杂系统的反馈结构。",
            }
        ],
        "notes": [
            {
                "bookTitle": "纳瓦尔宝典",
                "bookAuthor": "Eric Jorgenson",
                "markText": "判断力来自长期复利。",
                "reviewUrl": "https://weread.qq.com/note",
            }
        ],
        "highlights": [
            {
                "name": "写作是最小可行思考",
                "abstract": "把想法写下来，才知道自己是否真的想清楚。",
            }
        ],
    }

    entries = normalize_weread_entries(payload)

    assert len(entries) == 3
    assert entries[0]["title"] == "系统之美"
    assert entries[0]["author"] == "德内拉"
    assert entries[0]["cover_url"] == "https://img.example.com/book.jpg"
    assert entries[1]["title"] == "纳瓦尔宝典"
    assert entries[1]["raw_content"] == "判断力来自长期复利。"
    assert entries[2]["url"] == "https://weread.qq.com/r/weread-skills"


def test_normalize_weread_entries_accepts_nested_payload_and_strips_blank_url():
    payload = {
        "data": {
            "items": [
                {
                    "bookTitle": "长期主义",
                    "bookAuthor": "测试作者",
                    "markText": "真正的积累需要稳定输入。",
                    "reviewUrl": "        ",
                }
            ]
        },
        "result": {
            "books": [
                {
                    "title": "原则",
                    "summary": "把决策原则写下来。",
                    "bookUrl": " https://weread.qq.com/book/principles ",
                }
            ]
        },
    }

    entries = normalize_weread_entries(payload)

    assert len(entries) == 2
    assert entries[0]["title"] == "长期主义"
    assert entries[0]["author"] == "测试作者"
    assert entries[0]["url"] == "https://weread.qq.com/r/weread-skills"
    assert entries[1]["title"] == "原则"
    assert entries[1]["url"] == "https://weread.qq.com/book/principles"


def test_normalize_weread_entries_rejects_unknown_payload_shape():
    assert normalize_weread_entries({"data": {"items": "not-a-list"}}) == []
    assert normalize_weread_entries("not-a-payload") == []


def test_normalize_weread_entries_uses_sort_as_published_at():
    """sort 字段（Unix timestamp）应被解析为 published_at，保留微信读书排序顺序。"""
    import time

    ts = int(time.time()) - 3600  # 1 小时前
    payload = {
        "books": [
            {
                "title": "最近笔记的书",
                "sort": ts,
                "bookId": "b1",
            },
            {
                "title": "无 sort 的书",
                "bookId": "b2",
            },
        ],
    }

    entries = normalize_weread_entries(payload)

    assert len(entries) == 2
    # 有 sort 的：published_at 应为 sort 对应的时间
    assert entries[0]["title"] == "最近笔记的书"
    assert entries[0]["published_at"].timestamp() == ts
    # 无 sort 的：published_at 为 None，由 sync_weread_materials 决定回退策略
    assert entries[1]["title"] == "无 sort 的书"
    assert entries[1]["published_at"] is None
