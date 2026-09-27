"""#64 显式绑定流程回归（隔离 mock，不连任何数据库）。

覆盖 issue #64 验收四场景 + 会话不匹配：
- 正常绑定：step-up 密码 → bind/start 下发授权 URL → 回调落绑定、不建登录会话；
- 未 step-up 拒绝：密码错误 401，不产生绑定意图；
- 已有绑定冲突：link 抛 OAuthBindConflictError → 错误回跳；
- 未验证邮箱拒绝：与 #62 语义一致，在 userinfo 阶段即拒绝；
- 发起人与当前会话不一致：拒绝绑定。
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, unquote, urlsplit

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@localhost:5432/unused")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

from app.api.v1 import oauth as oauth_routes  # noqa: E402
from app.services.auth_service import OAuthBindConflictError  # noqa: E402

PUBLIC_ORIGIN = "https://topic.example.com"


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeGithub:
    def __init__(self, emails=None):
        self.callback_uri = None
        self.emails = (
            emails if emails is not None else [{"email": "private@example.com", "primary": True, "verified": True}]
        )

    async def get(self, endpoint, *, token):
        if endpoint == "user":
            return FakeResponse({"id": 42, "name": "Example", "login": "example", "email": None})
        if endpoint == "user/emails":
            return FakeResponse(self.emails)
        raise AssertionError(endpoint)

    async def authorize_redirect(self, request, redirect_uri):
        self.callback_uri = redirect_uri
        request.session["fake_state"] = "test-state"
        from fastapi.responses import RedirectResponse

        return RedirectResponse("https://github.com/login/oauth/authorize?state=test-state")

    async def authorize_access_token(self, request):
        assert request.session.get("fake_state") == "test-state"
        return {"access_token": "dummy", "token_type": "bearer"}


def make_bind_app(monkeypatch, provider_client, *, user, link=None, verify_ok=True, callback_user=None):
    """组装带依赖覆盖的 OAuth app（绑定流程专用）。"""
    monkeypatch.setattr(oauth_routes.settings, "SITE_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setattr(oauth_routes.settings, "OAUTH_FRONTEND_REDIRECT_URL", PUBLIC_ORIGIN + "/oauth/callback")
    monkeypatch.setattr(oauth_routes.settings, "APP_ENV", "production")
    monkeypatch.setattr(oauth_routes.settings, "AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(oauth_routes, "ENABLED_PROVIDERS", ["github"])
    monkeypatch.setattr(oauth_routes.oauth, "create_client", lambda _: provider_client)

    get_user = AsyncMock(return_value=SimpleNamespace(id=101, email="private@example.com"))
    create_session = AsyncMock(
        return_value=(
            "dummy-auth-cookie",
            SimpleNamespace(expires_at=datetime.now(UTC) + timedelta(hours=1)),
        )
    )
    monkeypatch.setattr(oauth_routes, "get_or_create_oauth_user", get_user)
    monkeypatch.setattr(oauth_routes, "create_session", create_session)

    monkeypatch.setattr(oauth_routes, "verify_password", lambda pwd, hash: verify_ok)
    link_mock = link if link is not None else AsyncMock(return_value=SimpleNamespace(id=7))
    monkeypatch.setattr(oauth_routes, "link_oauth_identity_to_user", link_mock)
    monkeypatch.setattr(oauth_routes, "get_optional_current_user", AsyncMock(return_value=callback_user or user))

    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="dummy-test-only-signing-secret",
        session_cookie="topiceye_oauth_state",
        https_only=True,
        same_site="lax",
    )
    app.include_router(oauth_routes.router, prefix="/api/v1")
    app.dependency_overrides[oauth_routes.get_current_user] = lambda: user

    async def fake_db():
        yield object()

    app.dependency_overrides[oauth_routes.get_db] = fake_db
    return app, get_user, create_session, link_mock


def _query(location: str) -> dict:
    return {k: v[0] for k, v in parse_qs(urlsplit(location).query).items()}


ADMIN = SimpleNamespace(id=101, email="admin@example.com", password_hash="x", role="admin")


@pytest.mark.asyncio
async def test_bind_start_rejects_wrong_password(monkeypatch):
    """未 step-up 拒绝：密码验证失败 401。"""
    provider = FakeGithub()
    app, *_ = make_bind_app(monkeypatch, provider, user=ADMIN, verify_ok=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
    ) as client:
        resp = await client.post("/api/v1/auth/oauth/github/bind/start", json={"password": "wrong"})
    assert resp.status_code == 401
    assert "step-up" in resp.json()["detail"] or "密码" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_bind_full_flow_links_without_login_session(monkeypatch):
    """正常绑定：start → 回调绑定成功，fragment 带 bind=linked 且不建登录会话。"""
    provider = FakeGithub()
    app, get_user, create_session, link = make_bind_app(monkeypatch, provider, user=ADMIN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        start = await client.post("/api/v1/auth/oauth/github/bind/start", json={"password": "correct"})
        assert start.status_code == 200
        assert start.json()["authorize_url"].startswith("https://github.com/login/oauth/authorize")

        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        location = callback.headers["location"]
        assert location.startswith(PUBLIC_ORIGIN + "/oauth/callback#")
        fragment = location.split("#", 1)[1]
        assert "bind=linked" in fragment
        assert "token=" not in fragment

    link.assert_awaited_once()
    kwargs = link.await_args.kwargs
    assert kwargs["provider"] == "github"
    assert kwargs["provider_user_id"] == "42"
    assert kwargs["email_verified"] is True
    # 绑定分支不触发登录：不建用户、不建会话
    get_user.assert_not_awaited()
    create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_bind_callback_conflict_returns_error(monkeypatch):
    """已有绑定冲突：link 抛冲突 → 错误回跳，且不建登录会话。"""
    provider = FakeGithub()
    link = AsyncMock(side_effect=OAuthBindConflictError("该账号已绑定此登录方式，请先解绑后再重新绑定"))
    app, get_user, create_session, _ = make_bind_app(monkeypatch, provider, user=ADMIN, link=link)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        await client.post("/api/v1/auth/oauth/github/bind/start", json={"password": "correct"})
        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        q = _query(callback.headers["location"])
        assert "已绑定" in unquote(q.get("error", ""))
    get_user.assert_not_awaited()
    create_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_bind_callback_unverified_email_rejected(monkeypatch):
    """未验证邮箱拒绝（#62 语义一致）：userinfo 阶段即拒绝，link 不被调用。"""
    provider = FakeGithub(emails=[{"email": "nope@example.com", "primary": True, "verified": False}])
    app, _, _, link = make_bind_app(monkeypatch, provider, user=ADMIN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        await client.post("/api/v1/auth/oauth/github/bind/start", json={"password": "correct"})
        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        q = _query(callback.headers["location"])
        assert "邮箱" in unquote(q.get("error", ""))
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_bind_callback_session_mismatch_rejected(monkeypatch):
    """发起人与当前会话不一致（intent user 101 ≠ 当前 202）：拒绝绑定。"""
    provider = FakeGithub()
    other = SimpleNamespace(id=202, email="other@example.com", password_hash="x")
    # 发起人 = ADMIN(101)，回调时会话本人 = other(202)
    app, _, _, link = make_bind_app(monkeypatch, provider, user=ADMIN, callback_user=other)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        # ADMIN（101）发起，但回调时 get_optional_current_user 返回 202
        start = await client.post("/api/v1/auth/oauth/github/bind/start", json={"password": "correct"})
        assert start.status_code == 200
        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        q = _query(callback.headers["location"])
        assert "重新发起绑定" in unquote(q.get("error", "")), callback.headers["location"]
    link.assert_not_awaited()


@pytest.mark.asyncio
async def test_callback_without_bind_intent_falls_back_to_login(monkeypatch):
    """无绑定意图（未经过 bind/start）时回调走原登录分支。"""
    provider = FakeGithub()
    app, get_user, create_session, link = make_bind_app(monkeypatch, provider, user=ADMIN)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        await client.get("/api/v1/auth/oauth/github/login")
        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        assert "token=" not in callback.headers["location"]
    get_user.assert_awaited_once()
    create_session.assert_awaited_once()
    link.assert_not_awaited()
