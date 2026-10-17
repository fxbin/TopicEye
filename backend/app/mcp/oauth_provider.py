"""MCP OAuth 授权服务器 — SDK 协议适配层。

实现 ``OAuthAuthorizationServerProvider`` 协议（mcp 2.3.0），全部业务
语义在 ``app/services/mcp_oauth_service.py``；本层与 ``auth.py`` 的
``TopicEyeTokenVerifier`` 同一角色：协议适配 + 每次调用独立 session
（成功 commit、异常 rollback），不携带业务逻辑。

协议方法与 SDK 的分工（SDK ``TokenHandler``/``AuthorizationHandler`` 已做：
PKCE S256 比对、code/refresh 过期与 client 归属、redirect_uri 一致性）：
- authorize：返回同意页 URL（302 目标）；
- exchange_authorization_code：消费 code（单次性）+ 签发 token 对；
- exchange_refresh_token：轮换（旧的原子撤销，重放连坐整族）；
- revoke_token：family 级联撤销（幂等）。
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from app.core.database import async_session
from app.services import mcp_oauth_service

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _db_session():
    """每次协议调用一个独立 session；成功 commit、异常 rollback（对齐 get_db）。"""
    async with async_session() as db:
        try:
            yield db
            await db.commit()
        except Exception:
            await db.rollback()
            raise


class TopicEyeOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """桥接 SDK 授权服务器协议与 TopicEye 存储；无状态，随请求建 session。"""

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        async with _db_session() as db:
            return await mcp_oauth_service.get_client(db, client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        async with _db_session() as db:
            await mcp_oauth_service.register_client(db, client_info)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        async with _db_session() as db:
            return await mcp_oauth_service.create_authorization_request(db, client_id=client.client_id, params=params)

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        async with _db_session() as db:
            return await mcp_oauth_service.load_authorization_code(
                db, client_id=client.client_id, code=authorization_code
            )

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        async with _db_session() as db:
            return await mcp_oauth_service.exchange_authorization_code(db, authorization_code)

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        async with _db_session() as db:
            return await mcp_oauth_service.load_refresh_token(db, client_id=client.client_id, token=refresh_token)

    async def exchange_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]
    ) -> OAuthToken:
        async with _db_session() as db:
            return await mcp_oauth_service.exchange_refresh_token(db, refresh_token, scopes)

    async def load_access_token(self, token: str) -> AccessToken | None:
        # /revoke 专用口径：client_id 必须是 OAuth 客户端 id（SDK 归属校验），
        # 不能复用 verifier 的 client_id=user.id 映射
        async with _db_session() as db:
            return await mcp_oauth_service.load_access_token(db, token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with _db_session() as db:
            await mcp_oauth_service.revoke_token_by_raw(db, token.token)
