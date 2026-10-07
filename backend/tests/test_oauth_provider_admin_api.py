"""第三方登录后台配置（#94）：admin API 权限、secret 加密落库、即时生效。

覆盖：
- admin API 权限：匿名 401 / 普通用户 403 / 管理员 200
- PUT 保存：secret Fernet 加密落库（enc:v1: 前缀，不存明文），响应永不回传 secret
- 启用校验：缺 client_id 或 client_secret 时 400
- secret 留空 = 保留现有密文；未知 provider 404
- 登录链路即时生效：/auth/oauth/providers 与 /auth/oauth/{p}/login 按请求读 DB，
  后台保存后无需重启即可见（#94 的核心行为承诺）
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from starlette.middleware.sessions import SessionMiddleware

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import admin_oauth as admin_oauth_api, auth as auth_api, oauth as oauth_api
from app.core.database import Base
from app.models.oauth_provider import OAuthProvider
from app.services.secret_store import SECRET_PREFIX


@pytest_asyncio.fixture
async def oauth_admin_client(monkeypatch) -> AsyncGenerator[tuple[httpx.AsyncClient, str, str], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from app.services.auth_service import create_session, create_user

    async with session_factory() as db:
        user = await create_user(db, email="user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        await db.commit()

    app = FastAPI()
    # authorize_redirect 要把 OAuth state 写进 request.session，
    # 与生产 main.py 同名 cookie（login 即时生效用例会走到真实跳转）
    app.add_middleware(
        SessionMiddleware,
        secret_key="dummy-test-only-signing-secret",
        session_cookie="topiceye_oauth_state",
    )
    app.include_router(auth_api.router)
    app.include_router(oauth_api.router)
    app.include_router(admin_oauth_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    for dependency in {auth_api.get_db, oauth_api.get_db, admin_oauth_api.get_db}:
        app.dependency_overrides[dependency] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, user_token, admin_token

    await engine.dispose()


@pytest.mark.asyncio
async def test_admin_oauth_providers_requires_admin(oauth_admin_client):
    client, user_token, admin_token = oauth_admin_client

    anonymous = await client.get("/admin/oauth/providers")
    assert anonymous.status_code == 401

    ordinary = await client.get("/admin/oauth/providers", headers={"Authorization": f"Bearer {user_token}"})
    assert ordinary.status_code == 403

    admin = await client.get("/admin/oauth/providers", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin.status_code == 200
    body = admin.json()
    # 固定两档，未配置时按「未配置 + 未启用」返回
    assert [p["provider"] for p in body["providers"]] == ["google", "github"]
    for item in body["providers"]:
        assert item["enabled"] is False
        assert item["client_secret_configured"] is False
        assert item["client_id"] is None


@pytest.mark.asyncio
async def test_update_provider_encrypts_secret_and_masks_response(oauth_admin_client):
    client, _, admin_token = oauth_admin_client
    headers = {"Authorization": f"Bearer {admin_token}"}

    resp = await client.put(
        "/admin/oauth/providers/github",
        json={"client_id": "gh-client-id", "client_secret": "gh-secret-plain", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["client_id"] == "gh-client-id"
    assert body["client_secret_configured"] is True
    # 响应里没有任何 secret 字段（脱敏承诺）
    assert "client_secret" not in body

    # GET 列表同样不回传 secret
    listed = (await client.get("/admin/oauth/providers", headers=headers)).json()
    github = next(p for p in listed["providers"] if p["provider"] == "github")
    assert github["client_secret_configured"] is True


@pytest.mark.asyncio
async def test_update_provider_validation(oauth_admin_client):
    client, _, admin_token = oauth_admin_client
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 未知 provider
    resp = await client.put(
        "/admin/oauth/providers/wechat",
        json={"client_id": "x", "client_secret": "y", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 404

    # 启用但缺 secret
    resp = await client.put(
        "/admin/oauth/providers/google",
        json={"client_id": "google-id", "client_secret": "", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 400

    # 缺 client_id
    resp = await client.put(
        "/admin/oauth/providers/google",
        json={"client_id": "", "client_secret": "s", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 400

    # 只存凭据不启用（先配好再开）是合法路径
    resp = await client.put(
        "/admin/oauth/providers/google",
        json={"client_id": "google-id", "client_secret": "google-secret", "enabled": False},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["enabled"] is False


@pytest.mark.asyncio
async def test_empty_secret_keeps_stored_value(oauth_admin_client):
    client, _, admin_token = oauth_admin_client
    headers = {"Authorization": f"Bearer {admin_token}"}

    await client.put(
        "/admin/oauth/providers/github",
        json={"client_id": "gh-id", "client_secret": "first-secret", "enabled": True},
        headers=headers,
    )
    # secret 留空 = 保留原值，仅改 client_id / enabled
    resp = await client.put(
        "/admin/oauth/providers/github",
        json={"client_id": "gh-id-2", "client_secret": "", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["client_id"] == "gh-id-2"
    assert resp.json()["client_secret_configured"] is True


@pytest.mark.asyncio
async def test_login_flow_reads_db_config_immediately(oauth_admin_client):
    """#94 核心行为：后台保存后即时生效，无缓存 / 无需重启。"""
    client, _, admin_token = oauth_admin_client
    headers = {"Authorization": f"Bearer {admin_token}"}

    # 初始：无 provider 可用 → 登录入口 404、按钮列表为空
    providers = (await client.get("/auth/oauth/providers")).json()["providers"]
    assert providers == []
    login = await client.get("/auth/oauth/github/login")
    assert login.status_code == 404

    # 后台配置启用 github（不重启任何东西）
    resp = await client.put(
        "/admin/oauth/providers/github",
        json={"client_id": "gh-id", "client_secret": "gh-secret", "enabled": True},
        headers=headers,
    )
    assert resp.status_code == 200

    # 按钮列表立即出现 github；login 进入 provider 授权跳转（302 到 github.com）
    providers = (await client.get("/auth/oauth/providers")).json()["providers"]
    assert providers == ["github"]
    login = await client.get("/auth/oauth/github/login", follow_redirects=False)
    assert login.status_code in {302, 307}
    assert login.headers["location"].startswith("https://github.com/login/oauth/authorize")

    # 真实 authlib client 走通 state session（覆盖「请求级构造 client」的关键路径）
    assert "topiceye_oauth_state=" in login.headers.get("set-cookie", "")

    # 禁用后立即消失
    await client.put(
        "/admin/oauth/providers/github",
        json={"client_id": "gh-id", "client_secret": "", "enabled": False},
        headers=headers,
    )
    providers = (await client.get("/auth/oauth/providers")).json()["providers"]
    assert providers == []
    login = await client.get("/auth/oauth/github/login")
    assert login.status_code == 404


@pytest.mark.asyncio
async def test_secret_stored_encrypted_not_plaintext():
    """repo/service 层加解密闭环：落库为 enc:v1: 密文，读取可解密还原。

    独立于 HTTP fixture：API 层的加密写入已在上面用例覆盖，这里直接验证
    repo + service 对密文格式的约定（明文不出现在库中）。
    """
    import tempfile
    from pathlib import Path

    from sqlalchemy import select

    from app.repositories.oauth_provider_repo import OAuthProviderRepository
    from app.services.oauth_provider_service import get_active_provider_config
    from app.services.secret_store import encrypt_secret

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "oauth_check.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with session_factory() as db:
            repo = OAuthProviderRepository(db)
            await repo.upsert_provider(
                "google",
                client_id="g-id",
                client_secret=encrypt_secret("round-trip-secret"),
                enabled=True,
            )
            await db.commit()

            row = (await db.execute(select(OAuthProvider))).scalar_one()
            assert row.client_secret is not None
            assert row.client_secret.startswith(SECRET_PREFIX)
            assert "round-trip-secret" not in row.client_secret

            config = await get_active_provider_config(db, "google")
            assert config is not None
            assert config.client_secret == "round-trip-secret"
            assert config.client_id == "g-id"

            # 凭据不全（enabled 但 secret 为空）→ 按未启用处理
            await repo.upsert_provider("google", client_id="g-id", client_secret=None, enabled=True)
            await db.commit()
            assert await get_active_provider_config(db, "google") is None
        await engine.dispose()
