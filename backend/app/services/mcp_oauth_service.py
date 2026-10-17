"""MCP OAuth 授权服务器业务编排。

实现官方 SDK ``OAuthAuthorizationServerProvider`` 协议背后的全部状态机：
动态客户端注册（secret Fernet 落库）、授权请求 → 同意 → 一次性授权码、
access/refresh 不透明 token 签发（raw 只回传一次、库存 sha256）、
refresh 轮换 + 重放检测（已轮换 refresh 被重放 → 撤销整个 family）、
RFC 7009 撤销与过期清理。

安全语义（SDK 侧已覆盖、此处只列 provider 责任）：
- 授权码单次使用：条件 UPDATE 的 rowcount 保证并发下只有一个消费者；
- PKCE S256 校验、code/refresh 归属 client、redirect_uri 一致性由 SDK
  ``TokenHandler`` 完成，本层在 exchange 时对 code_challenge 再核一遍防伪造模型；
- 所有 raw token / code 都是 ``secrets.token_urlsafe(32)``（256 bit），
  库里只见 sha256（复用 ``auth_service.hash_token``）。

事务边界：本层只 flush，不 commit——provider 适配层（每次调用独立
session，成功 commit）与 API 层（get_db）负责提交。
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, urlparse

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.core.config import settings
from app.models.mcp_oauth import MCPOAuthAuthorization, MCPOAuthToken
from app.repositories.mcp_oauth_authorization_repo import MCPOAuthAuthorizationRepository
from app.repositories.mcp_oauth_client_repo import MCPOAuthClientRepository
from app.repositories.mcp_oauth_token_repo import MCPOAuthTokenRepository
from app.services.auth_service import hash_token
from app.services.secret_store import decrypt_secret, encrypt_secret

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _epoch(dt: datetime) -> int:
    """datetime → epoch 秒（int；SDK 的 token 模型 expires_at 是整数）。

    SQLite 测试后端会丢 tzinfo，按 UTC 补回。
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return int(dt.timestamp())


def _expired(expires_at: datetime) -> bool:
    return _epoch(expires_at) < _now().timestamp()


def _site_base() -> str:
    """站点根 URL；未配置时回退本地开发地址（与 app.mcp.server._base_url 同口径）。"""
    return (settings.SITE_BASE_URL or "http://127.0.0.1:8000").rstrip("/")


def _consent_url(request_id: str) -> str:
    return f"{_site_base()}{settings.MCP_OAUTH_CONSENT_PATH}?request_id={quote(request_id)}"


def _load_scopes(raw: str | None) -> list[str]:
    return json.loads(raw) if raw else []


# ── 动态客户端注册（RFC 7591；SDK 已生成 client_id / secret，本层只持久化）──


async def register_client(db, client_info: OAuthClientInformationFull) -> None:
    """落库 DCR 客户端。secret 以 Fernet 密文单独存，元数据存 JSON。"""
    repo = MCPOAuthClientRepository(db)
    await repo.create(
        client_id=client_info.client_id,
        client_name=client_info.client_name,
        client_secret_enc=encrypt_secret(client_info.client_secret),
        metadata_json=client_info.model_dump_json(exclude={"client_secret"}),
    )


async def get_client(db, client_id: str) -> OAuthClientInformationFull | None:
    """按 client_id 取回注册信息；secret 解密后放回模型（ClientAuthenticator 用它比对）。"""
    repo = MCPOAuthClientRepository(db)
    row = await repo.get_by_client_id(client_id)
    if row is None:
        return None
    data = json.loads(row.metadata_json)
    data["client_secret"] = decrypt_secret(row.client_secret_enc)
    try:
        return OAuthClientInformationFull.model_validate(data)
    except Exception:
        logger.exception("MCP OAuth client %s 元数据损坏，无法还原", client_id)
        return None


# ── 授权请求 → 同意页 → 授权码 ─────────────────────────────────────────


async def create_authorization_request(
    db,
    *,
    client_id: str,
    params: AuthorizationParams,
    initiator_user_id: int | None,
) -> str:
    """/authorize 落一条 pending 授权请求，返回前端同意页 URL。

    ``initiator_user_id`` 是发起 /authorize 的浏览器会话用户（由宿主包装
    路由解析并经 contextvar 传入）；后续 info/approve/deny 只允许发起者
    本人操作，堵住「攻击者发起、诱导受害者批准」的同意页 CSRF 路径。
    """
    request_id = str(uuid.uuid4())
    row = MCPOAuthAuthorization(
        request_id=request_id,
        status="pending",
        client_id=client_id,
        initiator_user_id=initiator_user_id,
        scopes=json.dumps(params.scopes or []),
        state=params.state,
        code_challenge=params.code_challenge,
        redirect_uri=str(params.redirect_uri),
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource,
        expires_at=_now() + timedelta(seconds=settings.MCP_OAUTH_CODE_TTL_SECONDS),
    )
    db.add(row)
    await db.flush()
    return _consent_url(request_id)


async def _pending_row(db, request_id: str, *, acting_user_id: int) -> MCPOAuthAuthorization | None:
    """取 pending、未过期且**发起者是本人**的授权请求行；其余一律视为不存在。

    发起者为 NULL 的行（理论上只有绕过包装路由才会产生）同样拒绝——
    fail-closed，宁可要求重新发起也不给 approve-any 留缝。
    """
    row = await MCPOAuthAuthorizationRepository(db).get_by_request_id(request_id)
    if row is None or row.status != "pending" or _expired(row.expires_at):
        return None
    if row.initiator_user_id is None or row.initiator_user_id != acting_user_id:
        return None
    return row


async def get_authorization_info(db, request_id: str, *, viewer_user_id: int) -> dict | None:
    """同意页展示信息：应用名、主页、请求的 scope 与回调目标主机。"""
    row = await _pending_row(db, request_id, acting_user_id=viewer_user_id)
    if row is None:
        return None
    client = await get_client(db, row.client_id)
    return {
        "request_id": row.request_id,
        "client_name": (client.client_name if client else None) or row.client_id,
        "client_uri": client.client_uri if client else None,
        "scopes": _load_scopes(row.scopes),
        "redirect_host": urlparse(row.redirect_uri).hostname or "",
    }


async def approve_authorization(db, request_id: str, user_id: int) -> tuple[str, str] | None:
    """用户点「授权」：盖 code_hash、记 user，返回 (raw_code, 回调跳转地址)。

    只允许发起者本人批准（_pending_row 校验 initiator）；pending→approved
    用条件 UPDATE 原子迁移：双开标签页并发点「授权」只有一路拿到有效
    code（另一路 404），不会出现两枚 code 相互覆盖。
    """
    row = await _pending_row(db, request_id, acting_user_id=user_id)
    if row is None:
        return None
    code = secrets.token_urlsafe(32)
    # 批准后重新起算授权码 TTL
    ok = await MCPOAuthAuthorizationRepository(db).transition_to_approved(
        request_id,
        code_hash=hash_token(code),
        user_id=user_id,
        expires_at=_now() + timedelta(seconds=settings.MCP_OAUTH_CODE_TTL_SECONDS),
    )
    if not ok:
        return None
    redirect_to = construct_redirect_uri(row.redirect_uri, code=code, state=row.state)
    return code, redirect_to


async def deny_authorization(db, request_id: str, *, acting_user_id: int) -> str | None:
    """用户点「拒绝」：按 RFC 6749 带 error=access_denied 回调（仅发起者）。"""
    row = await _pending_row(db, request_id, acting_user_id=acting_user_id)
    if row is None:
        return None
    row.status = "denied"
    await db.flush()
    return construct_redirect_uri(row.redirect_uri, error="access_denied", state=row.state)


# ── 授权码交换 / token 签发与轮换 ──────────────────────────────────────


async def load_authorization_code(db, *, client_id: str, code: str) -> AuthorizationCode | None:
    authz_repo = MCPOAuthAuthorizationRepository(db)
    row = await authz_repo.get_by_code_hash(hash_token(code))
    if row is not None and row.status == "consumed":
        # 已消费的授权码再次出现 = 泄密信号（能走到消费完说明第一次兑换成功，
        # 而携带正确 code 的只有客户端或截获者）。当前只告警记录；整族撤销
        # 与 family 关联列随完整 scope 模型排期（issue #118，写工具前置 DoD）。
        logger.warning(
            "MCP OAuth 授权码重放信号：request_id=%s client=%s（token 未连坐撤销，见 issue #118）",
            row.request_id,
            row.client_id,
        )
    if row is None or row.status != "approved" or row.client_id != client_id or _expired(row.expires_at):
        return None
    return AuthorizationCode(
        code=code,
        scopes=_load_scopes(row.scopes),
        expires_at=_epoch(row.expires_at),
        client_id=row.client_id,
        code_challenge=row.code_challenge,
        redirect_uri=row.redirect_uri,
        redirect_uri_provided_explicitly=row.redirect_uri_provided_explicitly,
        resource=row.resource,
        subject=str(row.user_id) if row.user_id is not None else None,
    )


async def _issue_token_pair(
    db,
    *,
    client_id: str,
    user_id: int,
    scopes: list[str],
    resource: str | None,
    family_id: str | None = None,
) -> OAuthToken:
    """签发 access + refresh 一对（同一 family），raw 值只出现在返回值里。"""
    family_id = family_id or str(uuid.uuid4())
    now = _now()
    access_raw = secrets.token_urlsafe(32)
    refresh_raw = secrets.token_urlsafe(32)
    scopes_json = json.dumps(scopes) if scopes else None
    common = {
        "client_id": client_id,
        "user_id": user_id,
        "family_id": family_id,
        "scopes": scopes_json,
        "resource": resource,
    }
    db.add(
        MCPOAuthToken(
            token_hash=hash_token(access_raw),
            token_type="access",
            expires_at=now + timedelta(seconds=settings.MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS),
            **common,
        )
    )
    db.add(
        MCPOAuthToken(
            token_hash=hash_token(refresh_raw),
            token_type="refresh",
            expires_at=now + timedelta(days=settings.MCP_OAUTH_REFRESH_TOKEN_DAYS),
            **common,
        )
    )
    await db.flush()
    return OAuthToken(
        access_token=access_raw,
        expires_in=settings.MCP_OAUTH_ACCESS_TOKEN_TTL_SECONDS,
        scope=" ".join(scopes) if scopes else None,
        refresh_token=refresh_raw,
    )


async def exchange_authorization_code(db, auth_code: AuthorizationCode) -> OAuthToken:
    """消费授权码换 token 对；单次使用由条件 UPDATE 保证。"""
    authz_repo = MCPOAuthAuthorizationRepository(db)
    row = await authz_repo.get_by_code_hash(hash_token(auth_code.code))
    if row is None or row.user_id is None:
        raise TokenError("invalid_grant", "authorization code does not exist")
    if auth_code.code_challenge != row.code_challenge:
        # load 只从本行构造模型，challenge 不一致即伪造
        raise TokenError("invalid_grant", "authorization code challenge mismatch")
    if not await authz_repo.consume(row.request_id):
        raise TokenError("invalid_grant", "authorization code already used")
    return await _issue_token_pair(
        db,
        client_id=row.client_id,
        user_id=row.user_id,
        scopes=_load_scopes(row.scopes),
        resource=row.resource,
    )


async def load_refresh_token(db, *, client_id: str, token: str) -> RefreshToken | None:
    """加载 refresh；已撤销（含已轮换）的重放会连坐撤销整个 family。"""
    token_repo = MCPOAuthTokenRepository(db)
    row = await token_repo.get_by_token_hash(hash_token(token))
    if row is None or row.token_type != "refresh" or row.client_id != client_id:
        return None
    if row.revoked_at is not None:
        revoked = await token_repo.revoke_family(row.family_id)
        logger.warning("MCP OAuth refresh token 重放检测：family %s 撤销 %d 行", row.family_id, revoked)
        return None
    if _expired(row.expires_at):
        return None
    return RefreshToken(
        token=token,
        client_id=row.client_id,
        scopes=_load_scopes(row.scopes),
        expires_at=_epoch(row.expires_at),
        resource=row.resource,
        subject=str(row.user_id),
    )


async def exchange_refresh_token(db, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
    """轮换 refresh：原子撤销旧行后签发新对（同 family）。"""
    token_repo = MCPOAuthTokenRepository(db)
    row = await token_repo.get_by_token_hash(hash_token(refresh_token.token))
    if row is None or row.token_type != "refresh" or row.user_id is None:
        raise TokenError("invalid_grant", "refresh token does not exist")
    if not await token_repo.revoke_by_id_if_active(row.id):
        # 并发轮换：另一路已消费掉这枚 refresh
        raise TokenError("invalid_grant", "refresh token has been rotated")
    return await _issue_token_pair(
        db,
        client_id=row.client_id,
        user_id=row.user_id,
        scopes=scopes,
        resource=row.resource,
        family_id=row.family_id,
    )


# ── 资源服务器侧：token 解析与撤销 ────────────────────────────────────


async def resolve_access_token(db, token: str) -> AccessToken | None:
    """给 TopicEyeTokenVerifier 用：raw access token → SDK AccessToken。

    ``client_id`` 填 ``str(user.id)``（工具层 _caller_user_id 的约定），
    OAuth 客户端身份放 ``subject``/``claims`` 供审计。
    """
    row = await _active_access_row(db, token)
    if row is None:
        return None
    return AccessToken(
        token=token,
        client_id=str(row.user_id),
        scopes=_load_scopes(row.scopes),
        expires_at=_epoch(row.expires_at),
        resource=row.resource,
        subject=str(row.user_id),
        claims={"mcp_oauth_client_id": row.client_id},
    )


async def load_access_token(db, token: str) -> AccessToken | None:
    """给 SDK /revoke 处理器用：``client_id`` 必须是注册的 OAuth 客户端 id，
    否则 SDK 的归属校验（token.client_id == client.client_id）永远不成立，
    撤销会被静默跳过——这是与 resolve_access_token 分开两个函数的原因。
    """
    row = await _active_access_row(db, token)
    if row is None:
        return None
    return AccessToken(
        token=token,
        client_id=row.client_id,
        scopes=_load_scopes(row.scopes),
        expires_at=_epoch(row.expires_at),
        resource=row.resource,
        subject=str(row.user_id),
    )


async def _active_access_row(db, token: str) -> MCPOAuthToken | None:
    row = await MCPOAuthTokenRepository(db).get_by_token_hash(hash_token(token))
    if row is None or row.token_type != "access" or row.revoked_at is not None or _expired(row.expires_at):
        return None
    return row


async def revoke_token_by_raw(db, token: str) -> None:
    """RFC 7009：按 raw 值撤销（SDK 已校验归属 client），按 family 级联，幂等。"""
    token_repo = MCPOAuthTokenRepository(db)
    row = await token_repo.get_by_token_hash(hash_token(token))
    if row is not None:
        await token_repo.revoke_family(row.family_id)


# ── 清理（调度器每日执行）────────────────────────────────────────────


async def cleanup_expired(db) -> dict[str, int]:
    """删除过期授权行与已撤销且过期的 token 行（保留 1 天排障窗口）。"""
    cutoff = _now() - timedelta(days=1)
    authorizations = await MCPOAuthAuthorizationRepository(db).delete_stale(cutoff)
    tokens = await MCPOAuthTokenRepository(db).delete_stale(cutoff)
    if authorizations or tokens:
        logger.info("MCP OAuth 过期数据清理：authorizations=%d tokens=%d", authorizations, tokens)
    return {"authorizations": authorizations, "tokens": tokens}
