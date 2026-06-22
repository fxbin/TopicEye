from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app import main as app_main
from app.api.v1 import notifications as notifications_api, settings as settings_api
from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import Base, database_profile
from app.core.db_backend import create_database_profile
from app.models.app_setting import DEFAULT_RSSHUB_INSTANCES
from app.services import duckdb_service, notification_service


@pytest_asyncio.fixture
async def settings_notifications_client(monkeypatch) -> AsyncGenerator[httpx.AsyncClient, None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    monkeypatch.setattr(notification_service, "async_session", session_factory)

    app = FastAPI()
    app.include_router(settings_api.router)
    app.include_router(notifications_api.router)
    # /notifications 端点会读 current_user.id,裸 object() 没这属性,会 AttributeError。
    # 用 SimpleNamespace 提供最小 stub(id / is_active / is_superuser 等)。
    from types import SimpleNamespace

    _user_stub = SimpleNamespace(id=1, is_active=True, is_superuser=True, role="admin")
    app.dependency_overrides[get_current_admin_user] = lambda: _user_stub
    app.dependency_overrides[get_current_user] = lambda: _user_stub

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[settings_api.get_db] = override_get_db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    await engine.dispose()


@pytest.mark.asyncio
async def test_rsshub_settings_read_validate_and_update(settings_notifications_client: httpx.AsyncClient):
    defaults = await settings_notifications_client.get("/settings/rsshub/instances")
    assert defaults.status_code == 200
    assert defaults.json()["instances"] == []
    assert defaults.json()["default_instances"] == [item["url"] for item in DEFAULT_RSSHUB_INSTANCES]

    invalid = await settings_notifications_client.put(
        "/settings/rsshub/instances",
        json={"instances": [{"url": "ftp://rsshub.example", "enabled": True, "priority": 1}]},
    )
    assert invalid.status_code == 400

    updated = await settings_notifications_client.put(
        "/settings/rsshub/instances",
        json={
            "instances": [
                {
                    "url": " HTTPS://RSSHub.Example.com/ ",
                    "enabled": True,
                    "priority": 3,
                    "note": "测试实例",
                }
            ]
        },
    )
    assert updated.status_code == 200
    assert updated.json()["updated"] is True
    assert updated.json()["instances"][0]["url"] == "https://rsshub.example.com"

    current = await settings_notifications_client.get("/settings/rsshub/instances")
    assert current.status_code == 200
    assert current.json()["instances"] == [
        {
            "url": "https://rsshub.example.com",
            "enabled": True,
            "priority": 3,
            "note": "测试实例",
        }
    ]


@pytest.mark.asyncio
async def test_rsshub_settings_reject_duplicate_normalized_instances(
    settings_notifications_client: httpx.AsyncClient,
):
    duplicated = await settings_notifications_client.put(
        "/settings/rsshub/instances",
        json={
            "instances": [
                {"url": "https://rsshub.example.com/", "enabled": True, "priority": 1},
                {"url": "HTTPS://RSSHUB.EXAMPLE.COM", "enabled": True, "priority": 2},
            ]
        },
    )

    assert duplicated.status_code == 409
    assert "RSSHub instance already exists" in duplicated.json()["detail"]


@pytest.mark.asyncio
async def test_duckdb_status_reports_database_diagnostics(
    settings_notifications_client: httpx.AsyncClient,
    monkeypatch,
):
    class FakeAnalytics:
        def status(self):
            return {
                "status": "ok",
                "available": True,
                "backend": "sqlite",
                "extension": "sqlite",
                "attach_alias": "oltp_db",
                "mode": "duckdb_attach_read_only",
                "error": None,
            }

    monkeypatch.setattr(duckdb_service, "get_analytics", lambda: FakeAnalytics())

    response = await settings_notifications_client.get("/settings/duckdb/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["available"] is True
    assert payload["database"]["oltp"]["backend"] == database_profile.backend
    assert payload["database"]["analytics"]["backend"] == "duckdb"
    assert payload["database"]["analytics"]["attach_mode"] == "read_only"
    assert payload["note"] == "No sync needed; DuckDB reads the configured OLTP backend directly."


@pytest.mark.asyncio
async def test_duckdb_status_reports_unavailable_without_sqlalchemy_fallback_note(
    settings_notifications_client: httpx.AsyncClient,
    monkeypatch,
):
    class FakeAnalytics:
        def status(self):
            return {
                "status": "unavailable",
                "available": False,
                "backend": "sqlite",
                "extension": "sqlite",
                "attach_alias": "oltp_db",
                "mode": "duckdb_attach_read_only",
                "error": "sqlite extension unavailable",
            }

    monkeypatch.setattr(duckdb_service, "get_analytics", lambda: FakeAnalytics())

    response = await settings_notifications_client.get("/settings/duckdb/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["available"] is False
    assert "return 503" in payload["note"]
    assert "fallback" not in payload["note"].lower()
    assert "SQLAlchemy" not in payload["note"]


@pytest.mark.asyncio
async def test_duckdb_status_redacts_database_secret_on_unhandled_error(
    settings_notifications_client: httpx.AsyncClient,
    monkeypatch,
):
    url = "postgresql+asyncpg://topiceye:s3 cr'et@localhost:5432/topiceye"
    profile = create_database_profile(url)

    def fail_get_analytics():
        raise RuntimeError(f"cannot attach {url}; conninfo password='s3 cr\\'et'")

    monkeypatch.setattr(settings_api, "database_profile", profile)
    monkeypatch.setattr(duckdb_service, "get_analytics", fail_get_analytics)

    response = await settings_notifications_client.get("/settings/duckdb/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert "s3 cr'et" not in payload["error"]
    assert "s3 cr\\'et" not in payload["error"]
    assert "password=***" in payload["error"]
    assert "postgresql+asyncpg://topiceye:***@localhost:5432/topiceye" in payload["error"]


@pytest.mark.asyncio
async def test_health_redacts_duckdb_database_secret_on_error(monkeypatch):
    url = "postgresql+asyncpg://topiceye:s3 cr'et@localhost:5432/topiceye"
    profile = create_database_profile(url)

    def fail_get_analytics():
        raise RuntimeError(f"cannot attach {url}; conninfo password='s3 cr\\'et'")

    monkeypatch.setattr(app_main, "database_profile", profile)
    monkeypatch.setattr(duckdb_service, "get_analytics", fail_get_analytics)

    payload = await app_main.health_check()

    error = payload["database"]["duckdb"]["error"]
    assert payload["database"]["backend"] == "postgresql"
    assert payload["database"]["duckdb"]["status"] == "error"
    assert "s3 cr'et" not in error
    assert "s3 cr\\'et" not in error
    assert "password=***" in error
    assert "postgresql+asyncpg://topiceye:***@localhost:5432/topiceye" in error


@pytest.mark.asyncio
async def test_notification_api_lifecycle(settings_notifications_client: httpx.AsyncClient):
    created_list = await notification_service.push_notification(
        type="info",
        category="system",
        title="测试通知",
        message="通知内容",
        # 定向推送给 user_id=1(对应 fixture 里的 _user_stub.id=1)。
        # 不传 target_user_ids 走 broadcast,broadcast 不能被个人删除,
        # delete_notification 返回 False。
        target_user_ids=[1],
    )
    # push_notification 返回 list[Notification](per-user 批量),取第一条
    created = created_list[0]

    unread = await settings_notifications_client.get("/notifications/unread-count")
    assert unread.status_code == 200
    assert unread.json() == {"count": 1}

    listed = await settings_notifications_client.get("/notifications?unread=true")
    assert listed.status_code == 200
    assert listed.json()["count"] == 1
    assert listed.json()["notifications"][0]["id"] == created.id
    assert listed.json()["notifications"][0]["is_read"] is False

    marked = await settings_notifications_client.post(f"/notifications/{created.id}/read")
    assert marked.status_code == 200
    assert marked.json() == {"success": True}

    unread_after_mark = await settings_notifications_client.get("/notifications/unread-count")
    assert unread_after_mark.status_code == 200
    assert unread_after_mark.json() == {"count": 0}

    deleted = await settings_notifications_client.delete(f"/notifications/{created.id}")
    assert deleted.status_code == 200
    assert deleted.json() == {"success": True}
