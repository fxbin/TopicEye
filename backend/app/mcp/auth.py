"""MCP bearer token 校验 — 桥接到站点现有认证体系。

实现官方 SDK 的 ``TokenVerifier`` 协议，按序尝试两种口径：

1. **动态 OAuth access token**（浏览器弹窗登录流程签发，见
   ``app/mcp/oauth_provider.py``）：按 sha256 查 ``mcp_oauth_tokens``，
   校验未撤销/未过期；``client_id`` 填 ``str(user.id)``（工具层
   ``_caller_user_id`` 的约定），OAuth 客户端身份在 ``claims``。
2. **静态 token**：``auth_service.get_user_for_token`` 验证，接受与
   REST API 完全相同的两种 token——个人 API token
   （``POST /api/v1/me/api-tokens`` 自助创建）和浏览器 session token。

验证通过后映射为 ``AccessToken``，``client_id`` 携带 ``user.id``，工具层
据此取调用者身份（如按用户读自己的日报）。
"""

from __future__ import annotations

import logging

from mcp.server.auth.provider import AccessToken, TokenVerifier

from app.core.database import async_session
from app.services import mcp_oauth_service
from app.services.auth_service import get_user_for_token

logger = logging.getLogger(__name__)


class TopicEyeTokenVerifier(TokenVerifier):
    """Verify MCP bearer tokens against TopicEye's OAuth/static-token stores."""

    async def verify_token(self, token: str) -> AccessToken | None:
        # 1) 动态 OAuth access token（mcp_oauth_tokens 表，hash 索引直查）
        try:
            async with async_session() as db:
                access = await mcp_oauth_service.resolve_access_token(db, token)
            if access is not None:
                return access
        except Exception:
            # OAuth 表查不到不阻断静态 token 路径；真异常（库故障）由下方兜底统一记日志
            logger.debug("MCP OAuth access token 解析未命中或失败，回落静态 token", exc_info=True)

        # 2) 静态 token（session / 个人 API token）
        try:
            async with async_session() as db:
                user = await get_user_for_token(db, token)
                if user is None:
                    return None
                # session 关闭前读取，避免 detached 属性访问歧义
                user_id = user.id
                # get_user_for_token 会顺带滑动续期 session / 更新 API token
                # last_used_at；REST 路径靠 get_db 的 commit 落库，这里显式
                # commit，否则仅经 MCP 使用时这些副作用写会被静默回滚。
                await db.commit()
        except Exception:
            logger.exception("MCP token verification failed")
            return None
        return AccessToken(token=token, client_id=str(user_id), scopes=[])
