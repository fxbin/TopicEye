"""邮件服务 SMTP-only（#108）：Brevo 移除后的 API 与 factory 行为。

覆盖：
- PUT provider=brevo → 400（显式拒绝，不留兼容路径）
- GET 对存量 brevo 配置归一为未配置（provider=smtp + 字段全空）
- SMTP 正常配置/回读：密码加密落库、脱敏预览、明文不外泄
- PUT 密码留空 = 保留原值
- factory：存量 brevo 配置返回 None（显式降级）；SMTP 配置产出可用实例
"""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, settings as settings_api
from app.core.database import Base
from app.repositories.app_setting_repo import AppSettingRepository
from app.services.email.factory import get_email_provider
from app.services.email.smtp_provider import SmtpProvider
from app.services.secret_store import encrypt_secret


@pytest_asyncio.fixture
async def email_admin_client() -> AsyncGenerator[tuple[httpx.AsyncClient, str, dict], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.auth_service import create_session, create_user

    async with session_factory() as db:
        admin = await create_user(db, email="admin@example.com", password="Password123", role="admin")
        token, _ = await create_session(db, admin)
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(settings_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    for dependency in {auth_api.get_db, settings_api.get_db}:
        app.dependency_overrides[dependency] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, token, session_factory

    await engine.dispose()


SMTP_PAYLOAD = {
    "provider": "smtp",
    "from_email": "noreply@example.com",
    "from_name": "TopicEye",
    "smtp_host": "smtp.example.com",
    "smtp_port": 465,
    "smtp_username": "noreply@example.com",
    "smtp_password": "smtp-secret-plain",
    "smtp_use_ssl": True,
}


@pytest.mark.asyncio
async def test_put_brevo_rejected_with_explicit_error(email_admin_client):
    client, token, _ = email_admin_client
    resp = await client.put(
        "/settings/email-provider",
        json={**SMTP_PAYLOAD, "provider": "brevo", "api_key": "xkeysdk-legacy"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 400
    assert "Brevo 已于 #108 移除" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_put_smtp_requires_host_and_username(email_admin_client):
    client, token, _ = email_admin_client
    headers = {"Authorization": f"Bearer {token}"}

    missing_host = {k: v for k, v in SMTP_PAYLOAD.items() if k != "smtp_host"}
    resp = await client.put("/settings/email-provider", json=missing_host, headers=headers)
    assert resp.status_code == 400 and "SMTP 服务器" in resp.json()["detail"]

    missing_user = {k: v for k, v in SMTP_PAYLOAD.items() if k != "smtp_username"}
    resp = await client.put("/settings/email-provider", json=missing_user, headers=headers)
    assert resp.status_code == 400 and "SMTP 用户名" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_smtp_roundtrip_masks_password_and_keeps_on_empty(email_admin_client):
    client, token, _ = email_admin_client
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.put("/settings/email-provider", json=SMTP_PAYLOAD, headers=headers)
    assert resp.status_code == 200 and resp.json() == {"updated": True}

    got = (await client.get("/settings/email-provider", headers=headers)).json()
    assert got["provider"] == "smtp"
    assert got["smtp_host"] == "smtp.example.com"
    assert got["smtp_username"] == "noreply@example.com"
    assert got["smtp_password_configured"] is True
    assert "smtp-secret-plain" not in json.dumps(got)
    assert got["smtp_password_preview"].endswith("****")
    # api_key 相关字段已随 #108 删除
    assert "api_key_configured" not in got and "supported_providers" not in got

    # 密码留空 = 保留原值（只改发件人名称）
    resp = await client.put(
        "/settings/email-provider",
        json={**SMTP_PAYLOAD, "from_name": "改名", "smtp_password": ""},
        headers=headers,
    )
    assert resp.status_code == 200
    got = (await client.get("/settings/email-provider", headers=headers)).json()
    assert got["from_name"] == "改名"
    assert got["smtp_password_configured"] is True


@pytest.mark.asyncio
async def test_legacy_brevo_config_normalized_on_get_and_factory(email_admin_client):
    client, token, session_factory = email_admin_client
    headers = {"Authorization": f"Bearer {token}"}

    # 直接落一份存量 brevo 配置（模拟 #108 之前的部署）
    async with session_factory() as db:
        legacy = {
            "provider": "brevo",
            "from_email": "norevo@example.com",
            "from_name": "TopicEye",
            "api_key": encrypt_secret("legacy-brevo-key"),
        }
        await AppSettingRepository(db).upsert_setting(
            "email_provider_config", json.dumps(legacy), description="legacy brevo"
        )
        await db.commit()
        # factory：显式降级为不可用
        assert await get_email_provider(db) is None

    # GET：归一展示为未配置
    got = (await client.get("/settings/email-provider", headers=headers)).json()
    assert got["provider"] == "smtp"
    assert got["from_email"] == ""
    assert got["smtp_password_configured"] is False


@pytest.mark.asyncio
async def test_factory_builds_smtp_provider_from_stored_config(email_admin_client):
    _, token, session_factory = email_admin_client
    async with session_factory() as db:
        stored = {
            "provider": "smtp",
            "from_email": "noreply@example.com",
            "from_name": "TopicEye",
            "smtp_host": "smtp.example.com",
            "smtp_port": 465,
            "smtp_username": "noreply@example.com",
            "smtp_password": encrypt_secret("smtp-secret-plain"),
            "smtp_use_ssl": True,
        }
        await AppSettingRepository(db).upsert_setting("email_provider_config", json.dumps(stored), description="smtp")
        await db.commit()

        provider = await get_email_provider(db)
        assert isinstance(provider, SmtpProvider)
        assert provider._from_email == "noreply@example.com"

    # 不触网、只验证「存量配置 → 解密 → 构造」的工厂闭环
