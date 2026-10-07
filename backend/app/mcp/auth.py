"""MCP bearer token 校验 — 桥接到站点现有认证体系。

实现官方 SDK 的 ``TokenVerifier`` 协议，把 MCP 请求的 Bearer token 交给
``auth_service.get_user_for_token`` 验证，因此接受与 REST API 完全相同的
两种 token：个人 API token（``POST /api/v1/me/api-tokens`` 自助创建）和
浏览器 session token。验证通过后映射为 ``AccessToken``，``client_id``
携带 ``user.id``，工具层据此取调用者身份（如按用户读自己的日报）。
"""

from __future__ import annotations

import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.core.database import async_session
from app.services.auth_service import get_user_for_token

logger = logging.getLogger(__name__)


class TopicEyeTokenVerifier(TokenVerifier):
    """Verify MCP bearer tokens against TopicEye's session/API-token store."""

    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            async with async_session() as db:
                user = await get_user_for_token(db, token)
                if user is None:
                    return None
                # session 关闭前读取，避免 detached 属性访问歧义
                user_id = user.id
        except Exception:
            logger.exception("MCP token verification failed")
            return None
        return AccessToken(token=token, client_id=str(user_id), scopes=[])
