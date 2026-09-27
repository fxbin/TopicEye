"""Isolated mocked OAuth regression tests. No live providers or database access.

Placed outside tests/ deliberately: tests/conftest.py has database cleanup
fixtures and must never run against a production database.
Run with an isolated dummy DATABASE_URL.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://dummy:dummy@localhost:5432/unused")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import RedirectResponse  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402
from starlette.requests import Request  # noqa: E402

from app.api.v1 import oauth as oauth_routes  # noqa: E402

PUBLIC_ORIGIN = "https://topic.example.com"


class FakeResponse:
    def __init__(self, data):
        self.data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self.data


class FakeGithub:
    def __init__(self, public_email=None, emails=None):
        self.calls = []
        self.callback_uri = None
        self.public_email = public_email
        self.emails = (
            emails if emails is not None else [{"email": "private@example.com", "primary": True, "verified": True}]
        )

    async def get(self, endpoint, *, token):
        self.calls.append(endpoint)
        if endpoint == "user":
            return FakeResponse({"id": 42, "name": "Example", "login": "example", "email": self.public_email})
        if endpoint == "user/emails":
            return FakeResponse(self.emails)
        raise AssertionError(endpoint)

    async def authorize_redirect(self, request, redirect_uri):
        self.callback_uri = redirect_uri
        request.session["fake_state"] = "test-state"
        return RedirectResponse("https://github.com/login/oauth/authorize?state=test-state")

    async def authorize_access_token(self, request):
        assert request.session.get("fake_state") == "test-state"
        assert request.query_params["state"] == "test-state"
        return {"access_token": "dummy", "token_type": "bearer"}


@pytest.mark.asyncio
async def test_github_private_email_verified_primary():
    client = FakeGithub()
    result = await oauth_routes._extract_userinfo(client, "github", {"access_token": "dummy"})
    assert result == ("42", "private@example.com", True, "Example")
    assert client.calls == ["user", "user/emails"]


@pytest.mark.asyncio
async def test_github_unverified_primary_rejected():
    client = FakeGithub(
        public_email="public@example.com", emails=[{"email": "public@example.com", "primary": True, "verified": False}]
    )
    with pytest.raises(oauth_routes._OAuthUserInfoError, match="可验证的主邮箱"):
        await oauth_routes._extract_userinfo(client, "github", {"access_token": "dummy"})


@pytest.mark.asyncio
async def test_github_secondary_verified_cannot_override_primary():
    client = FakeGithub(
        emails=[
            {"email": "unverified@example.com", "primary": True, "verified": False},
            {"email": "secondary@example.com", "primary": False, "verified": True},
        ]
    )
    with pytest.raises(oauth_routes._OAuthUserInfoError, match="可验证的主邮箱"):
        await oauth_routes._extract_userinfo(client, "github", {"access_token": "dummy"})


@pytest.mark.asyncio
async def test_google_prefers_verified_oidc_token_userinfo():
    client = SimpleNamespace(userinfo=AsyncMock(side_effect=AssertionError("Unexpected userinfo request")))
    token = {"userinfo": {"sub": "google-id", "email": "google@example.com", "email_verified": True, "name": "Google"}}
    assert await oauth_routes._extract_userinfo(client, "google", token) == (
        "google-id",
        "google@example.com",
        True,
        "Google",
    )
    client.userinfo.assert_not_awaited()


def internal_request():
    return Request(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "scheme": "http",
            "server": ("backend", 8000),
            "root_path": "",
            "path": "/api/v1/auth/oauth/github/login",
            "query_string": b"",
            "headers": [(b"host", b"backend:8000")],
            "client": ("127.0.0.1", 1234),
        }
    )


def test_callback_uses_public_origin_over_internal_proxy(monkeypatch):
    monkeypatch.setattr(oauth_routes.settings, "SITE_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setattr(oauth_routes.settings, "APP_ENV", "production")
    assert oauth_routes._backend_callback_url(internal_request(), "github") == (
        PUBLIC_ORIGIN + "/api/v1/auth/oauth/github/callback"
    )


def test_production_rejects_http_callback_origin(monkeypatch):
    monkeypatch.setattr(oauth_routes.settings, "SITE_BASE_URL", "http://topic.example.com")
    monkeypatch.setattr(oauth_routes.settings, "APP_ENV", "production")
    with pytest.raises(HTTPException):
        oauth_routes._backend_callback_url(internal_request(), "github")


def make_app(monkeypatch, provider, provider_client):
    monkeypatch.setattr(oauth_routes.settings, "SITE_BASE_URL", PUBLIC_ORIGIN)
    monkeypatch.setattr(oauth_routes.settings, "OAUTH_FRONTEND_REDIRECT_URL", PUBLIC_ORIGIN + "/oauth/callback")
    monkeypatch.setattr(oauth_routes.settings, "APP_ENV", "production")
    monkeypatch.setattr(oauth_routes.settings, "AUTH_COOKIE_SECURE", True)
    monkeypatch.setattr(oauth_routes, "ENABLED_PROVIDERS", [provider])
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
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="dummy-test-only-signing-secret",
        session_cookie="topiceye_oauth_state",
        https_only=True,
        same_site="lax",
    )
    app.include_router(oauth_routes.router, prefix="/api/v1")

    async def fake_db():
        yield object()

    app.dependency_overrides[oauth_routes.get_db] = fake_db
    return app, get_user, create_session


@pytest.mark.asyncio
async def test_mock_github_authorization_state_callback_and_auth_cookies(monkeypatch):
    provider = FakeGithub()
    app, get_user, create_session = make_app(monkeypatch, "github", provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        login = await client.get("/api/v1/auth/oauth/github/login")
        assert login.status_code in {302, 307}
        assert provider.callback_uri == PUBLIC_ORIGIN + "/api/v1/auth/oauth/github/callback"
        assert "topiceye_oauth_state=" in login.headers.get("set-cookie", "")
        assert "secure" in login.headers.get("set-cookie", "").lower()
        callback = await client.get("/api/v1/auth/oauth/github/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        location = callback.headers["location"]
        assert location.startswith(PUBLIC_ORIGIN + "/oauth/callback#")
        assert "topiceye_auth=" in callback.headers.get("set-cookie", "")
        # #63：fragment 不含任何凭证，只带非敏感状态
        fragment = location.split("#", 1)[1]
        assert "token=" not in fragment
        assert "provider=github" in fragment
        assert "expires_at=" in fragment
        assert get_user.await_args.kwargs["email_verified"] is True
        create_session.assert_awaited_once()


class FakeGoogle(FakeGithub):
    async def authorize_redirect(self, request, redirect_uri):
        self.callback_uri = redirect_uri
        request.session["fake_state"] = "test-state"
        return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?state=test-state")

    async def authorize_access_token(self, request):
        assert request.session["fake_state"] == request.query_params["state"] == "test-state"
        return {
            "access_token": "dummy",
            "userinfo": {"sub": "g123", "email": "g@example.com", "email_verified": True, "name": "Google"},
        }

    async def userinfo(self, *, token):
        raise AssertionError("OIDC token already includes userinfo")


@pytest.mark.asyncio
async def test_mock_google_authorization_state_callback_and_auth_cookies(monkeypatch):
    provider = FakeGoogle()
    app, get_user, create_session = make_app(monkeypatch, "google", provider)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=PUBLIC_ORIGIN,
        follow_redirects=False,
    ) as client:
        login = await client.get("/api/v1/auth/oauth/google/login")
        assert login.status_code in {302, 307}
        assert provider.callback_uri == PUBLIC_ORIGIN + "/api/v1/auth/oauth/google/callback"
        callback = await client.get("/api/v1/auth/oauth/google/callback?code=dummy&state=test-state")
        assert callback.status_code == 302
        location = callback.headers["location"]
        assert location.startswith(PUBLIC_ORIGIN + "/oauth/callback#")
        assert "topiceye_auth=" in callback.headers.get("set-cookie", "")
        # #63：fragment 不含任何凭证，只带非敏感状态
        fragment = location.split("#", 1)[1]
        assert "token=" not in fragment
        assert "provider=google" in fragment
        assert "expires_at=" in fragment
        create_session.assert_awaited_once()
