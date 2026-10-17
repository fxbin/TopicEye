"""MCP OAuth HTTP 全链路测试 — AS 端点挂在 FastAPI 根路径的真实编排。

复用 test_mcp_server.py 的 ASGITransport + session_manager.run 模式，把
完整 OAuth 2.1 舞步走一遍（对 /mcp 的调用证明 OAuth token 与 RS 侧
verifier 全链路打通）：

DCR(/register) → /authorize 302 同意页 → approve(会话认证) → /token
PKCE 换取 → **Bearer access token 打 /mcp/ 跑工具** → refresh 轮换 →
旧 refresh 重放 400 + family 连坐 → /revoke → 401；外加两个 RFC 8414 /
RFC 9728 元数据端点断言与 deny 分支、错误 PKCE 分支。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from mcp_types import (
    CLIENT_CAPABILITIES_META_KEY,
    CLIENT_INFO_META_KEY,
    LATEST_PROTOCOL_VERSION,
    PROTOCOL_VERSION_META_KEY,
)

from app.api.v1 import mcp_oauth as mcp_oauth_api
from app.core.database import get_db
from app.mcp import auth as mcp_auth, authorize_route as mcp_authorize_route, oauth_provider as mcp_provider
from app.mcp.server import build_oauth_routes, build_streamable_http_app, mcp_server
from app.services.auth_service import create_session, create_user

REDIRECT_URI = "http://127.0.0.1:8765/callback"
CLIENT_NAME = "http-oauth-client"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _modern_stateless_request(tool: str, arguments: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool,
            "arguments": arguments,
            "_meta": {
                PROTOCOL_VERSION_META_KEY: LATEST_PROTOCOL_VERSION,
                CLIENT_CAPABILITIES_META_KEY: {},
                CLIENT_INFO_META_KEY: {"name": "pytest", "version": "0.0"},
            },
        },
    }


def _make_app(test_session_factory) -> FastAPI:
    """宿主 app 的真实挂法：AS 路由在根、/mcp 子应用、consent 走 /api/v1。"""

    async def _override_get_db():
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app = FastAPI()
    app.include_router(mcp_oauth_api.router, prefix="/api/v1")
    app.router.routes.extend(build_oauth_routes())
    app.mount("/mcp", build_streamable_http_app())
    app.dependency_overrides[get_db] = _override_get_db
    return app


@pytest.fixture(autouse=True)
def _patch_provider_sessions(test_session_factory, monkeypatch):
    """provider / verifier / authorize 包装路由都走独立 session 工厂（测试内存库）。"""
    monkeypatch.setattr(mcp_provider, "async_session", test_session_factory)
    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)
    monkeypatch.setattr(mcp_authorize_route, "async_session", test_session_factory)


async def _seed_session_user(test_session_factory) -> tuple[int, str]:
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-http-oauth@t", password="pw")
        await db.commit()
        raw_token, _row = await create_session(db, user)
        await db.commit()
        return user.id, raw_token


async def _register_client(client: AsyncClient) -> str:
    resp = await client.post(
        "/register",
        json={
            "client_name": CLIENT_NAME,
            "redirect_uris": [REDIRECT_URI],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["client_id"]
    assert body.get("client_secret") is None  # 公共客户端（method=none）不发 secret
    return body["client_id"]


async def _start_authorization(
    client: AsyncClient, client_id: str, challenge: str, session_token: str | None = None
) -> str:
    """发起 /authorize；带会话即绑定发起者（生产路径恒带，见 authorize_route）。"""
    headers = {"Authorization": f"Bearer {session_token}"} if session_token else None
    resp = await client.get(
        "/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "http-state",
        },
        headers=headers,
    )
    assert resp.status_code == 302, resp.text
    location = resp.headers["location"]
    assert "/mcp/authorize?request_id=" in location
    return location.split("request_id=")[1]


async def _approve(client: AsyncClient, request_id: str, session_token: str) -> str:
    resp = await client.post(
        "/api/v1/mcp-oauth/approve",
        json={"request_id": request_id},
        headers={"Authorization": f"Bearer {session_token}"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["redirect_to"]


async def _exchange_code(client: AsyncClient, client_id: str, code: str, verifier: str) -> dict:
    resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "client_id": client_id,
            "code_verifier": verifier,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["token_type"] == "Bearer"
    return body


async def _full_grant(client: AsyncClient, session_token: str) -> tuple[str, dict]:
    """DCR → authorize → approve → token，返回 (client_id, tokens)。"""
    client_id = await _register_client(client)
    verifier, challenge = _pkce()
    request_id = await _start_authorization(client, client_id, challenge, session_token)
    redirect_to = await _approve(client, request_id, session_token)
    code = parse_qs(urlparse(redirect_to).query)["code"][0]
    tokens = await _exchange_code(client, client_id, code, verifier)
    return client_id, tokens


# ── 完整舞蹈 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_oauth_dance_to_mcp_tool_call(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with (
        mcp_server.session_manager.run(),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        client_id, tokens = await _full_grant(client, session_token)

        # 同意页信息端点也顺带验证（认证 + 内容）
        verifier2, challenge2 = _pkce()
        request_id2 = await _start_authorization(client, client_id, challenge2, session_token)
        info = await client.get(
            "/api/v1/mcp-oauth/authorize-info",
            params={"request_id": request_id2},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert info.status_code == 200
        assert info.json()["client_name"] == CLIENT_NAME
        assert info.json()["redirect_host"] == "127.0.0.1"

        # OAuth access token 打 /mcp/：RS verifier → 工具执行全链路
        resp = await client.post(
            "/mcp/",
            json=_modern_stateless_request(
                "score_items",
                {"items": [{"content_id": 9001, "title": "MCP OAuth 全链路", "info_density": 70}]},
            ),
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert resp.status_code == 200, resp.text
        result = resp.json()["result"]
        assert result["isError"] is False
        assert result["structuredContent"]["results"][0]["content_id"] == 9001


@pytest.mark.asyncio
async def test_refresh_rotation_and_replay_revokes_family_http(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with (
        mcp_server.session_manager.run(),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        client_id, tokens = await _full_grant(client, session_token)

        # 轮换成功
        first = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert first.status_code == 200, first.text
        rotated = first.json()

        # 旧 refresh 重放 → 400 invalid_grant，且 family 连坐（新 access 也失效）
        replay = await client.post(
            "/token",
            data={"grant_type": "refresh_token", "refresh_token": tokens["refresh_token"], "client_id": client_id},
        )
        assert replay.status_code == 400
        assert replay.json()["error"] == "invalid_grant"

        dead = await client.post(
            "/mcp/",
            json=_modern_stateless_request("score_items", {"items": [{"content_id": 1}]}),
            headers={"Authorization": f"Bearer {rotated['access_token']}"},
        )
        assert dead.status_code == 401


@pytest.mark.asyncio
async def test_revoke_kills_access_token(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with (
        mcp_server.session_manager.run(),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        client_id, tokens = await _full_grant(client, session_token)

        # SDK RevocationRequest 把 client_secret 声明为必填（可空）——公共
        # 客户端按惯例带空值；authenticator 对 method=none 的客户端忽略该字段
        revoked = await client.post(
            "/revoke",
            data={
                "token": tokens["access_token"],
                "client_id": client_id,
                "token_type_hint": "access_token",
                "client_secret": "",
            },
        )
        assert revoked.status_code == 200  # RFC 7009：未知 token 也 200，幂等

        dead = await client.post(
            "/mcp/",
            json=_modern_stateless_request("score_items", {"items": [{"content_id": 1}]}),
            headers={"Authorization": f"Bearer {tokens['access_token']}"},
        )
        assert dead.status_code == 401


# ── 负向分支 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_wrong_pkce_verifier_rejected(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        _verifier, challenge = _pkce()
        request_id = await _start_authorization(client, client_id, challenge, session_token)
        redirect_to = await _approve(client, request_id, session_token)
        code = parse_qs(urlparse(redirect_to).query)["code"][0]

        wrong = secrets.token_urlsafe(48)
        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": wrong,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_authorization_code_single_use_http(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id, _tokens = await _full_grant(client, session_token)
        verifier, challenge = _pkce()
        request_id = await _start_authorization(client, client_id, challenge, session_token)
        redirect_to = await _approve(client, request_id, session_token)
        code = parse_qs(urlparse(redirect_to).query)["code"][0]

        first = await _exchange_code(client, client_id, code, verifier)
        assert first["access_token"]
        second = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert second.status_code == 400
        assert second.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_deny_flow(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        _verifier, challenge = _pkce()
        request_id = await _start_authorization(client, client_id, challenge, session_token)

        resp = await client.post(
            "/api/v1/mcp-oauth/deny",
            json={"request_id": request_id},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert resp.status_code == 200
        redirect_to = resp.json()["redirect_to"]
        assert "error=access_denied" in redirect_to and "state=http-state" in redirect_to

        # deny 后请求终态：approve / authorize-info 都 404
        gone = await client.post(
            "/api/v1/mcp-oauth/approve",
            json={"request_id": request_id},
            headers={"Authorization": f"Bearer {session_token}"},
        )
        assert gone.status_code == 404


@pytest.mark.asyncio
async def test_consent_endpoints_require_auth(test_session_factory):
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/v1/mcp-oauth/authorize-info", params={"request_id": "whatever"})
        assert resp.status_code == 401
        resp = await client.post("/api/v1/mcp-oauth/approve", json={"request_id": "whatever"})
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_authorize_rejects_unregistered_redirect_uri(test_session_factory):
    """开放重定向守卫：redirect_uri 不在客户端注册列表内必须 400，不落库。"""
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    _verifier, challenge = _pkce()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        resp = await client.get(
            "/authorize",
            headers={"Authorization": f"Bearer {session_token}"},
            params={
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:9999/evil-callback",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"
        assert "not registered" in resp.json()["error_description"]


@pytest.mark.asyncio
async def test_token_rejects_redirect_uri_mismatch(test_session_factory):
    """/token 的 redirect_uri 必须与 /authorize 时一致（SDK 比对存储行）。"""
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        verifier, challenge = _pkce()
        request_id = await _start_authorization(client, client_id, challenge, session_token)
        redirect_to = await _approve(client, request_id, session_token)
        code = parse_qs(urlparse(redirect_to).query)["code"][0]

        resp = await client.post(
            "/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": "http://127.0.0.1:8765/other",
                "client_id": client_id,
                "code_verifier": verifier,
            },
        )
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_client(test_session_factory):
    _user_id, session_token = await _seed_session_user(test_session_factory)
    transport = ASGITransport(app=_make_app(test_session_factory))
    _verifier, challenge = _pkce()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/authorize",
            headers={"Authorization": f"Bearer {session_token}"},
            params={
                "client_id": "no-such-client",
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        # client 未注册 → 直接 400 JSON（无回调可跳）
        assert resp.status_code == 400
        assert resp.json()["error"] == "invalid_request"


# ── 元数据端点（RFC 8414 / RFC 9728）───────────────────────────────────


@pytest.mark.asyncio
async def test_authorization_server_metadata(test_session_factory):
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/.well-known/oauth-authorization-server")
        assert resp.status_code == 200
        meta = resp.json()
        assert meta["authorization_endpoint"].endswith("/authorize")
        assert meta["token_endpoint"].endswith("/token")
        assert meta["registration_endpoint"].endswith("/register")
        assert meta["revocation_endpoint"].endswith("/revoke")
        assert "S256" in meta["code_challenge_methods_supported"]
        assert "authorization_code" in meta["grant_types_supported"]
        assert "refresh_token" in meta["grant_types_supported"]


@pytest.mark.asyncio
async def test_protected_resource_metadata(test_session_factory):
    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/.well-known/oauth-protected-resource/mcp")
        assert resp.status_code == 200
        meta = resp.json()
        assert meta["resource"].endswith("/mcp")
        assert meta["authorization_servers"], "应指回 AS（issuer）"


@pytest.mark.asyncio
async def test_static_token_still_works_alongside_oauth(test_session_factory):
    """存量静态 token（个人 API token）在 OAuth 上线后行为不变。"""
    from app.services.auth_service import create_api_token

    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-static@t", password="pw")
        await db.commit()
        raw_token, _record = await create_api_token(db, user_id=user.id, name="http static")
        await db.commit()

    transport = ASGITransport(app=_make_app(test_session_factory))
    async with (
        mcp_server.session_manager.run(),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        resp = await client.post(
            "/mcp/",
            json=_modern_stateless_request("score_items", {"items": [{"content_id": 7}]}),
            headers={"Authorization": f"Bearer {raw_token}"},
        )
        assert resp.status_code == 200
        assert resp.json()["result"]["isError"] is False


# ── 发起者绑定（issue #116 圆桌裁定 ①：堵 approve-any 冒用路径）────────


@pytest.mark.asyncio
async def test_authorize_anonymous_redirects_to_login(test_session_factory):
    """匿名浏览器发起 /authorize → 302 登录页，returnTo 带完整查询串可续传。"""
    transport = ASGITransport(app=_make_app(test_session_factory))
    _verifier, challenge = _pkce()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        resp = await client.get(
            "/authorize",
            params={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": "anon",
            },
        )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "/login?returnTo=" in location
        # returnTo 是编码后的完整 /authorize 地址（含查询串）
        assert "%2Fauthorize%3F" in location


@pytest.mark.asyncio
async def test_authorize_post_anonymous_rejected(test_session_factory):
    """POST /authorize 匿名 → 400（POST 无法断点续传，不做登录重定向）。"""
    transport = ASGITransport(app=_make_app(test_session_factory))
    _verifier, challenge = _pkce()
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        resp = await client.post(
            "/authorize",
            data={
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400


@pytest.mark.asyncio
async def test_only_initiator_can_view_or_approve(test_session_factory):
    """发起者绑定：B 看不到 A 发起的请求（info 404），approve 也 404；A 本人正常。"""
    from app.services.auth_service import create_session, create_user

    async with test_session_factory() as db:
        alice = await create_user(db, email="bind-alice@t", password="pw")
        bob = await create_user(db, email="bind-bob@t", password="pw")
        await db.commit()
        alice_token, _r1 = await create_session(db, alice)
        bob_token, _r2 = await create_session(db, bob)
        await db.commit()

    transport = ASGITransport(app=_make_app(test_session_factory))
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client_id = await _register_client(client)
        _verifier, challenge = _pkce()
        request_id = await _start_authorization(client, client_id, challenge, alice_token)

        # B（非发起者）看不到也批不了
        info_b = await client.get(
            "/api/v1/mcp-oauth/authorize-info",
            params={"request_id": request_id},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert info_b.status_code == 404
        approve_b = await client.post(
            "/api/v1/mcp-oauth/approve",
            json={"request_id": request_id},
            headers={"Authorization": f"Bearer {bob_token}"},
        )
        assert approve_b.status_code == 404

        # A（发起者）正常批准（code 正常签发；兑换链路由 _full_grant 覆盖）
        redirect_to = await _approve(client, request_id, alice_token)
        assert "code=" in redirect_to
