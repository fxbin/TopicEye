"""OAuth 登录路由（Google / GitHub）。

流程：
  1. 前端整页跳转 GET /auth/oauth/{provider}/login → 后端 302 到 provider 授权页
  2. provider 回调 GET /auth/oauth/{provider}/callback → 换 token + 拉 userinfo
  3. 解析为本地 User（自动合并同邮箱账号）+ 建 session
  4. 302 到前端回调页，token 走 URL fragment（不进 server log / Referer）
"""
from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.oauth import ENABLED_PROVIDERS, oauth
from app.services.auth_service import (
    OAuthAccountConflictError,
    create_session,
    get_or_create_oauth_user,
)

router = APIRouter(prefix="/auth/oauth", tags=["auth"])
logger = logging.getLogger(__name__)


def _is_provider_enabled(provider: str) -> bool:
    return provider in ENABLED_PROVIDERS


def _backend_callback_url(request: Request, provider: str) -> str:
    """构造 provider 应回调回的后端地址（保持当前 host/scheme）。

    优先用 request.base_url，去掉末尾斜杠后拼接。
    开发态：http://127.0.0.1:8102/api/v1/auth/oauth/{provider}/callback
    """
    base = str(request.base_url).rstrip("/")
    return f"{base}/api/v1/auth/oauth/{provider}/callback"


def _frontend_redirect(fragment: str | None = None, error: str | None = None) -> RedirectResponse:
    """构造跳回前端的响应。token 走 fragment，错误走 query。"""
    target = settings.OAUTH_FRONTEND_REDIRECT_URL
    if error:
        sep = "&" if "?" in target else "?"
        target = f"{target}{sep}{urlencode({'error': error})}"
    elif fragment:
        target = f"{target}#{fragment}"
    return RedirectResponse(url=target, status_code=status.HTTP_302_FOUND)


# ── 跳转到 provider 授权页 ──────────────────────────────────────────


@router.get("/{provider}/login")
async def oauth_login(request: Request, provider: str):
    """整页跳转到 provider 的 OAuth 授权页。前端用 window.location.href 直接跳。"""
    if not _is_provider_enabled(provider):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"OAuth provider '{provider}' not enabled")
    client = oauth.create_client(provider)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"OAuth provider '{provider}' not registered")
    redirect_uri = _backend_callback_url(request, provider)
    return await client.authorize_redirect(request, redirect_uri)


# ── provider 回调 ─────────────────────────────────────────────────


@router.get("/{provider}/callback")
async def oauth_callback(request: Request, provider: str, db: AsyncSession = Depends(get_db)):
    """provider 授权后回调：换 token → 拉 userinfo → 建/找 User → 建 session → 302 回前端。"""
    if not _is_provider_enabled(provider):
        return _frontend_redirect(error=f"OAuth provider '{provider}' not enabled")

    client = oauth.create_client(provider)
    if client is None:
        return _frontend_redirect(error=f"OAuth provider '{provider}' not registered")

    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:
        logger.warning("OAuth token exchange failed: provider=%s, ip=%s, exc=%s", provider, request.client.host if request.client else "unknown", exc)
        return _frontend_redirect(error=f"OAuth 授权失败：{exc}")

    try:
        provider_user_id, email, email_verified, display_name = await _extract_userinfo(
            client, provider, token
        )
    except _OAuthUserInfoError as exc:
        logger.warning("OAuth userinfo failed: provider=%s, exc=%s", provider, exc)
        return _frontend_redirect(error=str(exc))

    if not email or not provider_user_id:
        return _frontend_redirect(error="OAuth 身份信息不完整（缺少邮箱或用户 ID）")

    try:
        user = await get_or_create_oauth_user(
            db,
            provider=provider,
            provider_user_id=str(provider_user_id),
            email=email,
            email_verified=email_verified,
            display_name=display_name,
        )
    except OAuthAccountConflictError as exc:
        logger.warning("OAuth account conflict: provider=%s, email=%s, exc=%s", provider, email, exc)
        return _frontend_redirect(error=str(exc))

    access_token, session = await create_session(db, user)
    logger.info("OAuth login success: provider=%s, user_id=%d, email=%s", provider, user.id, email)

    # token 走 fragment，expires_at 一并传给前端用于过期判断
    fragment = urlencode({
        "token": access_token,
        "expires_at": session.expires_at.isoformat(),
    })
    return _frontend_redirect(fragment=fragment)


# ── 已启用 provider 列表（前端据此渲染按钮）──────────────────────────


@router.get("/providers")
async def oauth_providers() -> dict[str, list[str]]:
    """返回已配置 client_id 的 provider 列表。"""
    return {"providers": list(ENABLED_PROVIDERS)}


# ── userinfo 解析（provider 差异隔离在这里）─────────────────────────


class _OAuthUserInfoError(Exception):
    """拉取 OAuth userinfo 失败的内部异常。"""


async def _extract_userinfo(
    client: Any, provider: str, token: dict
) -> tuple[str, str, bool, str | None]:
    """从 provider 拉取 (provider_user_id, email, email_verified, display_name)。

    - Google：OIDC userinfo 直接含 sub/email/email_verified/name
    - GitHub：/user 只有 id/login/name，email 字段可能为 null 且不保证已验证，
              必须额外调 /user/emails 取 primary+verified 的邮箱。
    """
    if provider == "google":
        userinfo = await client.userinfo(token=token)
        provider_user_id = str(userinfo.get("sub") or "")
        email = userinfo.get("email") or ""
        # Google 返回 email_verified 可能是 bool 或字符串 "true"
        email_verified_raw = userinfo.get("email_verified")
        email_verified = email_verified_raw is True or str(email_verified_raw).lower() == "true"
        display_name = userinfo.get("name")
        return provider_user_id, email, email_verified, display_name

    if provider == "github":
        # authorize_access_token 已拿到 GitHub access token
        github_token = token.get("access_token") or ""
        userinfo = await client.userinfo(token=token)
        provider_user_id = str(userinfo.get("id") or "")
        display_name = userinfo.get("name") or userinfo.get("login")

        # 优先用 userinfo.email（若有且已验证）
        email = userinfo.get("email") or ""
        email_verified = False
        if email:
            # GitHub userinfo 不带 verified 标志，仍需查 /user/emails 确认
            email, email_verified = await _resolve_github_email(client, github_token)

        if not email:
            raise _OAuthUserInfoError("GitHub 账号未公开邮箱且无可验证邮箱，无法登录")
        if not email_verified:
            raise _OAuthUserInfoError("GitHub 账号邮箱未验证，无法用于登录")

        return provider_user_id, email, email_verified, display_name

    raise _OAuthUserInfoError(f"不支持的 OAuth provider: {provider}")


async def _resolve_github_email(client: Any, access_token: str) -> tuple[str, bool]:
    """调 GitHub /user/emails 取第一个 primary+verified 的邮箱。"""
    if not access_token:
        return "", False
    resp = await client.get(
        "user/emails",
        token={"access_token": access_token, "token_type": "bearer"},
    )
    resp.raise_for_status()
    emails = resp.json()
    if not isinstance(emails, list):
        return "", False
    for entry in emails:
        if entry.get("primary") and entry.get("verified"):
            return entry.get("email", ""), True
    return "", False
