"""MCP OAuth /authorize 包装路由 — 把发起者绑定到授权请求。

SDK 的 ``AuthorizationHandler.handle`` → ``provider.authorize(client, params)``
链路拿不到 HTTP 请求，无法在读 cookie 的同时落库；本模块用**同路径抢先
注册**的包装路由补上这一环：

1. 从 cookie（``topiceye_auth``）或 Authorization 头解析当前会话用户
   （与 REST 完全同一套 token：session / 个人 API token）；
2. 未登录：GET 302 到前端登录页并带 ``returnTo`` 回跳（授权本就要求
   资源所有者在场，RFC 6749 §4.1；POST 无法断点续传，直接 400）；
3. 已登录：把 user.id 放进 ContextVar 后委托 SDK AuthorizationHandler，
   provider 侧 ``authorize()`` 读 ContextVar 存入授权行；此后
   info/approve/deny 只认发起者本人（见 mcp_oauth_service._pending_row）。

这条绑定堵住「攻击者匿名发起 /authorize、诱导已登录受害者点同意页」
的 approve-any 路径：request_id 天然在发起者手里，不可猜/TTL/一次性
都不构成缓解（issue #116 圆桌裁定，Round 1 共识）。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from urllib.parse import quote

from mcp.server.auth.handlers.authorize import AuthorizationHandler
from mcp.server.auth.provider import OAuthAuthorizationServerProvider
from mcp.server.transport_security import DEFAULT_MAX_REQUEST_BODY_SIZE, RequestBodyLimitMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Route, request_response

from app.core.config import settings
from app.core.database import async_session
from app.services.auth_service import get_user_for_token

logger = logging.getLogger(__name__)

#: 发起 /authorize 的会话用户 id；包装路由写入、provider.authorize 读取。
#: ContextVar 在同一请求任务内传播（endpoint → SDK handler → provider）。
initiator_user_id_var: ContextVar[int | None] = ContextVar("mcp_oauth_initiator_user_id", default=None)


def _site_base() -> str:
    return (settings.SITE_BASE_URL or "http://127.0.0.1:8000").rstrip("/")


def _extract_session_token(request: Request) -> str | None:
    """与 app.api.v1.auth 同一口径：Bearer 头优先，回落 auth cookie。"""
    auth_header = request.headers.get("authorization", "")
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        if token:
            return token
    return request.cookies.get(settings.AUTH_COOKIE_NAME)


async def _resolve_initiator(request: Request) -> int | None:
    token = _extract_session_token(request)
    if not token:
        return None
    try:
        async with async_session() as db:
            user = await get_user_for_token(db, token)
            if user is None:
                return None
            user_id = user.id
            # get_user_for_token 的滑动续期等副作用显式落库（同 verifier 口径）
            await db.commit()
    except Exception:
        logger.exception("MCP OAuth /authorize 发起者解析失败，按未登录处理")
        return None
    return user_id


async def _authorize_endpoint(request: Request) -> Response:
    initiator = await _resolve_initiator(request)
    if initiator is None:
        if request.method == "GET":
            # 断点续传：登录后回到 /authorize 继续绑定与授权（returnTo 已含完整查询串）
            target = f"{_site_base()}{request.url.path}"
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return RedirectResponse(
                url=f"{_site_base()}/login?returnTo={quote(target, safe='')}",
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse({"detail": "MCP 授权需要登录会话，请通过浏览器发起"}, status_code=400)

    initiator_user_id_var.set(initiator)
    provider: OAuthAuthorizationServerProvider = request.scope["mcp_oauth_provider"]
    return await AuthorizationHandler(provider).handle(request)


def make_authorize_route(provider: OAuthAuthorizationServerProvider) -> Route:
    """构建替代 SDK 原生 /authorize 的包装路由（同路径、同方法面）。"""

    async def endpoint(request: Request) -> Response:
        request.scope["mcp_oauth_provider"] = provider
        return await _authorize_endpoint(request)

    return Route(
        "/authorize",
        endpoint=RequestBodyLimitMiddleware(request_response(endpoint), DEFAULT_MAX_REQUEST_BODY_SIZE),
        methods=["GET", "POST"],
    )
