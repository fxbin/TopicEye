"""MCP OAuth service 测试 — 授权码 / token 轮换 / 重放检测 / verifier 混合口径。

口径（in-memory SQLite，``test_session_factory``）：
1. DCR 客户端往返：register_client → get_client（secret 解密、元数据还原）。
2. 授权生命周期：create → info → approve → load → exchange（单次性）→ deny。
3. refresh 轮换 + 重放连坐：旧 refresh 重放 → family 整体撤销（新 access 一并失效）。
4. resolve_access_token / TopicEyeTokenVerifier：OAuth token 与静态 API token 并存。
5. cleanup_expired 清理终态行。
"""

from __future__ import annotations

import base64
import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from mcp.server.auth.provider import AuthorizationParams, TokenError
from mcp.shared.auth import OAuthClientInformationFull

from app.mcp import auth as mcp_auth
from app.mcp.auth import TopicEyeTokenVerifier
from app.services import mcp_oauth_service as svc
from app.services.auth_service import create_api_token, create_session, create_user

REDIRECT_URI = "http://127.0.0.1:8765/callback"
RESOURCE = "http://localhost:3000/mcp"


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


def _client_info(name: str = "pytest-mcp") -> OAuthClientInformationFull:
    return OAuthClientInformationFull(
        client_id=str(uuid.uuid4()),
        client_secret="unit-test-secret-" + secrets.token_hex(16),
        redirect_uris=[REDIRECT_URI],
        grant_types=["authorization_code", "refresh_token"],
        response_types=["code"],
        client_name=name,
        token_endpoint_auth_method="none",
        scope="",
    )


def _params(challenge: str) -> AuthorizationParams:
    return AuthorizationParams(
        state="st4te-xyz",
        scopes=None,
        code_challenge=challenge,
        redirect_uri=REDIRECT_URI,
        redirect_uri_provided_explicitly=True,
        resource=RESOURCE,
    )


async def _approved_code(db, user_id: int, client: OAuthClientInformationFull) -> str:
    """走完整路径拿到已批准的授权码（发起者=user_id 本人）。"""
    _verifier, challenge = _pkce()
    consent_url = await svc.create_authorization_request(
        db, client_id=client.client_id, params=_params(challenge), initiator_user_id=user_id
    )
    request_id = consent_url.split("request_id=")[1]
    result = await svc.approve_authorization(db, request_id, user_id)
    assert result is not None
    return result[0]


# ── 1. DCR 客户端往返 ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_client_roundtrip(test_session_factory):
    client = _client_info()
    async with test_session_factory() as db:
        await svc.register_client(db, client)
        await db.commit()

        loaded = await svc.get_client(db, client.client_id)
        assert loaded is not None
        assert loaded.client_id == client.client_id
        assert loaded.client_secret == client.client_secret  # 解密还原
        assert loaded.redirect_uris == client.redirect_uris
        assert loaded.grant_types == client.grant_types
        assert loaded.token_endpoint_auth_method == "none"

        assert await svc.get_client(db, "no-such-client") is None


@pytest.mark.asyncio
async def test_client_secret_not_stored_plaintext(test_session_factory):
    """库里只有 Fernet 密文（enc:v1:），raw secret 不落盘。"""
    client = _client_info()
    async with test_session_factory() as db:
        await svc.register_client(db, client)
        await db.commit()
        from app.repositories.mcp_oauth_client_repo import MCPOAuthClientRepository

        row = await MCPOAuthClientRepository(db).get_by_client_id(client.client_id)
        assert row is not None
        assert row.client_secret_enc is not None
        assert row.client_secret_enc.startswith("enc:v1:")
        assert client.client_secret not in row.client_secret_enc
        assert client.client_secret not in row.metadata_json


# ── 2. 授权生命周期 ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorization_lifecycle(test_session_factory):
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-oauth@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        await db.commit()

        verifier, challenge = _pkce()
        consent_url = await svc.create_authorization_request(
            db, client_id=client.client_id, params=_params(challenge), initiator_user_id=user.id
        )
        assert "/mcp/authorize?request_id=" in consent_url
        request_id = consent_url.split("request_id=")[1]

        # 同意页信息（仅发起者可见）
        info = await svc.get_authorization_info(db, request_id, viewer_user_id=user.id)
        assert info is not None
        assert info["client_name"] == "pytest-mcp"
        assert info["redirect_host"] == "127.0.0.1"

        # 未批准前按 code 查不到
        assert await svc.load_authorization_code(db, client_id=client.client_id, code="whatever") is None

        # 批准 → 拿到 code 与回调地址
        result = await svc.approve_authorization(db, request_id, user.id)
        assert result is not None
        code, redirect_to = result
        assert code in redirect_to and "state=st4te-xyz" in redirect_to

        # 批准后重复 approve / info 都失效（一次性）
        assert await svc.approve_authorization(db, request_id, user.id) is None
        assert await svc.get_authorization_info(db, request_id, viewer_user_id=user.id) is None

        # load → exchange
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        assert auth_code is not None
        assert auth_code.code_challenge == challenge
        assert auth_code.resource == RESOURCE
        assert auth_code.subject == str(user.id)

        tokens = await svc.exchange_authorization_code(db, auth_code)
        assert tokens.access_token and tokens.refresh_token
        assert tokens.expires_in > 0

        # 授权码单次性：再 exchange 抛 invalid_grant
        with pytest.raises(TokenError):
            await svc.exchange_authorization_code(db, auth_code)

        # access token 可解析（client_id=user.id，OAuth 客户端身份在 claims）
        access = await svc.resolve_access_token(db, tokens.access_token)
        assert access is not None
        assert access.client_id == str(user.id)
        assert access.claims == {"mcp_oauth_client_id": client.client_id}

        # 换个 client 查 code → None（归属校验）
        assert await svc.load_authorization_code(db, client_id="other-client", code=code) is None


@pytest.mark.asyncio
async def test_authorization_deny(test_session_factory):
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-deny@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        _verifier, challenge = _pkce()
        consent_url = await svc.create_authorization_request(
            db, client_id=client.client_id, params=_params(challenge), initiator_user_id=user.id
        )
        request_id = consent_url.split("request_id=")[1]

        redirect_to = await svc.deny_authorization(db, request_id, acting_user_id=user.id)
        assert redirect_to is not None
        assert "error=access_denied" in redirect_to and "state=st4te-xyz" in redirect_to
        # deny 后请求终态
        assert await svc.deny_authorization(db, request_id, acting_user_id=user.id) is None


@pytest.mark.asyncio
async def test_authorization_code_expiry(test_session_factory):
    """授权码 10 分钟 TTL：过期后 load 拒绝（SDK 侧还会再核一次 expires_at）。"""
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-ttl@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)

        from app.repositories.mcp_oauth_authorization_repo import MCPOAuthAuthorizationRepository

        row = await MCPOAuthAuthorizationRepository(db).get_by_code_hash(svc.hash_token(code))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.flush()

        assert await svc.load_authorization_code(db, client_id=client.client_id, code=code) is None


@pytest.mark.asyncio
async def test_concurrent_approve_only_one_wins(test_session_factory):
    """双开标签页并发批准：原子迁移后只有一路拿到有效 code（另一路 None）。"""
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-race@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        _verifier, challenge = _pkce()
        consent_url = await svc.create_authorization_request(
            db, client_id=client.client_id, params=_params(challenge), initiator_user_id=user.id
        )
        request_id = consent_url.split("request_id=")[1]

        first = await svc.approve_authorization(db, request_id, user.id)
        second = await svc.approve_authorization(db, request_id, user.id)
        assert first is not None
        assert second is None
        # 幸存的 code 可正常兑换
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=first[0])
        tokens = await svc.exchange_authorization_code(db, auth_code)
        assert tokens.access_token


# ── 3. refresh 轮换与重放连坐 ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_rotation_and_replay_revokes_family(test_session_factory):
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-rotate@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        tokens = await svc.exchange_authorization_code(db, auth_code)

        # 轮换：旧 refresh → 新对
        refresh = await svc.load_refresh_token(db, client_id=client.client_id, token=tokens.refresh_token)
        assert refresh is not None
        rotated = await svc.exchange_refresh_token(db, refresh, refresh.scopes or [])
        assert rotated.access_token != tokens.access_token
        assert rotated.refresh_token != tokens.refresh_token

        # 新 access token 可用
        assert await svc.resolve_access_token(db, rotated.access_token) is not None

        # 重放旧 refresh → 触发 family 整体撤销（新 access 也失效）
        replay = await svc.load_refresh_token(db, client_id=client.client_id, token=tokens.refresh_token)
        assert replay is None
        assert await svc.resolve_access_token(db, rotated.access_token) is None
        assert await svc.resolve_access_token(db, tokens.access_token) is None


@pytest.mark.asyncio
async def test_expired_access_token_unresolvable(test_session_factory):
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-exp@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        tokens = await svc.exchange_authorization_code(db, auth_code)

        # 直接把 access 行改成已过期
        from app.repositories.mcp_oauth_token_repo import MCPOAuthTokenRepository

        row = await MCPOAuthTokenRepository(db).get_by_token_hash(svc.hash_token(tokens.access_token))
        assert row is not None
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await db.flush()
        assert await svc.resolve_access_token(db, tokens.access_token) is None


# ── 4. verifier 混合口径 ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_verifier_accepts_oauth_then_static_token(test_session_factory, monkeypatch):
    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)

    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-mixed@t", password="pw")
        await db.commit()
        raw_static, _record = await create_api_token(db, user_id=user.id, name="static")
        await db.commit()

        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        tokens = await svc.exchange_authorization_code(db, auth_code)
        await db.commit()
        user_id = user.id

    verifier = TopicEyeTokenVerifier()
    # OAuth access token：client_id=user.id，带过期时间
    access = await verifier.verify_token(tokens.access_token)
    assert access is not None
    assert access.client_id == str(user_id)
    assert access.expires_at is not None
    # 静态 API token 回落路径依然工作（无过期时间）
    static_access = await verifier.verify_token(raw_static)
    assert static_access is not None
    assert static_access.client_id == str(user_id)
    assert static_access.expires_at is None
    # 乱码 token
    assert await verifier.verify_token("garbage-token") is None


@pytest.mark.asyncio
async def test_verifier_accepts_session_token_still(test_session_factory, monkeypatch):
    """浏览器 session token（另一类静态 token）也仍走通。"""
    monkeypatch.setattr(mcp_auth, "async_session", test_session_factory)
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-session@t", password="pw")
        await db.commit()
        raw_session, _session_row = await create_session(db, user)
        await db.commit()

    access = await TopicEyeTokenVerifier().verify_token(raw_session)
    assert access is not None
    assert access.client_id == str(user.id)


# ── 5. 清理 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_expired(test_session_factory):
    async with test_session_factory() as db:
        user = await create_user(db, email="mcp-clean@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        tokens = await svc.exchange_authorization_code(db, auth_code)

        # 把时间拨回 2 天前（授权行终态 + token 已撤销过期）
        from sqlalchemy import update

        from app.models.mcp_oauth import MCPOAuthAuthorization, MCPOAuthToken
        from app.repositories.mcp_oauth_token_repo import MCPOAuthTokenRepository

        await db.execute(
            update(MCPOAuthAuthorization)
            .where(MCPOAuthAuthorization.status.in_(("consumed", "denied")))
            .values(updated_at=datetime.now(UTC) - timedelta(days=2), expires_at=datetime.now(UTC) - timedelta(days=2))
        )
        refresh_row = await MCPOAuthTokenRepository(db).get_by_token_hash(svc.hash_token(tokens.refresh_token))
        await db.execute(
            update(MCPOAuthToken)
            .where(MCPOAuthToken.id == refresh_row.id)
            .values(revoked_at=datetime.now(UTC) - timedelta(days=2), expires_at=datetime.now(UTC) - timedelta(days=2))
        )
        await db.commit()

        removed = await svc.cleanup_expired(db)
        assert removed["authorizations"] >= 1
        assert removed["tokens"] >= 1


# ── 发起者绑定 + 重放信号 ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_initiator_binding_blocks_non_initiator(test_session_factory):
    """发起者绑定：非发起者 info/approve/deny 全部 None；无发起者的行 fail-closed。"""
    async with test_session_factory() as db:
        alice = await create_user(db, email="init-alice@t", password="pw")
        bob = await create_user(db, email="init-bob@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        _verifier, challenge = _pkce()
        consent_url = await svc.create_authorization_request(
            db, client_id=client.client_id, params=_params(challenge), initiator_user_id=alice.id
        )
        request_id = consent_url.split("request_id=")[1]

        # B（非发起者）三路全拒绝
        assert await svc.get_authorization_info(db, request_id, viewer_user_id=bob.id) is None
        assert await svc.approve_authorization(db, request_id, bob.id) is None
        assert await svc.deny_authorization(db, request_id, acting_user_id=bob.id) is None

        # A（发起者）正常
        assert await svc.get_authorization_info(db, request_id, viewer_user_id=alice.id) is not None
        result = await svc.approve_authorization(db, request_id, alice.id)
        assert result is not None

        # 发起者为 NULL 的行（绕过包装路由才会产生）同样 fail-closed
        consent_url2 = await svc.create_authorization_request(
            db, client_id=client.client_id, params=_params(challenge), initiator_user_id=None
        )
        request_id2 = consent_url2.split("request_id=")[1]
        assert await svc.get_authorization_info(db, request_id2, viewer_user_id=alice.id) is None
        assert await svc.approve_authorization(db, request_id2, alice.id) is None


@pytest.mark.asyncio
async def test_consumed_code_replay_logs_warning(test_session_factory, caplog):
    """已消费 code 重放：返回 None 且留下泄密信号告警（连坐撤销见 issue #118）。"""
    import logging

    async with test_session_factory() as db:
        user = await create_user(db, email="replay@t", password="pw")
        await db.commit()
        client = _client_info()
        await svc.register_client(db, client)
        code = await _approved_code(db, user.id, client)
        auth_code = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        tokens = await svc.exchange_authorization_code(db, auth_code)
        assert tokens.access_token

        with caplog.at_level(logging.WARNING, logger="app.services.mcp_oauth_service"):
            replayed = await svc.load_authorization_code(db, client_id=client.client_id, code=code)
        assert replayed is None
        assert any("授权码重放信号" in r.message for r in caplog.records)
