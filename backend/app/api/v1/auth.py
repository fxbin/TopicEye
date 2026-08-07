from __future__ import annotations

import logging
from collections import deque
from time import monotonic

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.request_utils import client_ip
from app.models.user import User, UserRole
from app.schemas.auth import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthTokenResponse,
    ChangePasswordRequest,
    SendCodeRequest,
    UserResponse,
)
from app.services.auth_service import (
    authenticate_user,
    change_password,
    create_session,
    create_user,
    get_user_by_email,
    get_user_for_token,
    refresh_session,
    revoke_token,
)
from app.services.email_verification_service import (
    CodeRateLimitedError,
    EmailNotConfiguredError,
    InvalidCodeError,
    VerificationError,
    send_verification_code,
    verify_code,
)

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)
_AUTH_RATE_WINDOW_SECONDS = 60.0
_AUTH_RATE_BUCKETS: dict[str, deque[float]] = {}


def _enforce_auth_rate_limit(request: Request, *, action: str, max_attempts: int) -> None:
    if max_attempts <= 0:
        return
    now = monotonic()
    cutoff = now - _AUTH_RATE_WINDOW_SECONDS
    key = f"{action}:{client_ip(request)}"
    bucket = _AUTH_RATE_BUCKETS.setdefault(key, deque())
    while bucket and bucket[0] <= cutoff:
        bucket.popleft()
    if len(bucket) >= max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many authentication attempts; please try again later",
        )
    bucket.append(now)


async def enforce_register_rate_limit(request: Request) -> None:
    _enforce_auth_rate_limit(
        request,
        action="register",
        max_attempts=settings.AUTH_REGISTER_ATTEMPTS_PER_MINUTE,
    )


async def enforce_login_rate_limit(request: Request) -> None:
    _enforce_auth_rate_limit(
        request,
        action="login",
        max_attempts=settings.AUTH_LOGIN_ATTEMPTS_PER_MINUTE,
    )


async def enforce_send_code_rate_limit(request: Request) -> None:
    _enforce_auth_rate_limit(
        request,
        action="send_code",
        max_attempts=settings.AUTH_SEND_CODE_ATTEMPTS_PER_MINUTE,
    )


async def enforce_refresh_rate_limit(request: Request) -> None:
    _enforce_auth_rate_limit(
        request,
        action="refresh",
        max_attempts=settings.AUTH_REFRESH_ATTEMPTS_PER_MINUTE,
    )


# ── Cookie helpers ──────────────────────────────────────────────────
#
# Token 通过 HttpOnly cookie 下发，前端 JS 无法读取，降低 XSS 窃取风险。
# 同时保留 Bearer header 支持（API 客户端 / CLI）。
# 两个辅助 cookie（非 HttpOnly）让前端判断登录状态与过期时间。

_COOKIE_KWARGS = {
    "secure": settings.AUTH_COOKIE_SECURE,
    "samesite": settings.AUTH_COOKIE_SAMESITE,
    "domain": settings.AUTH_COOKIE_DOMAIN or None,
}


def _set_auth_cookies(response: Response, token: str, expires_at) -> None:
    """在 response 上设置 HttpOnly auth cookie + 辅助 cookie。"""
    max_age = settings.SESSION_DAYS * 86400
    response.set_cookie(
        settings.AUTH_COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        path="/",
        **_COOKIE_KWARGS,
    )
    # 非 HttpOnly：前端 JS 据此判断是否已登录
    response.set_cookie(
        settings.AUTH_PRESENCE_COOKIE_NAME,
        "1",
        max_age=max_age,
        httponly=False,
        path="/",
        **_COOKIE_KWARGS,
    )
    # 非 HttpOnly：前端 JS 用于 refresh 判断
    response.set_cookie(
        settings.AUTH_EXPIRES_COOKIE_NAME,
        expires_at.isoformat() if hasattr(expires_at, "isoformat") else str(expires_at),
        max_age=max_age,
        httponly=False,
        path="/",
        **_COOKIE_KWARGS,
    )


def _clear_auth_cookies(response: Response) -> None:
    """清除所有 auth 相关 cookie。"""
    for name in (
        settings.AUTH_COOKIE_NAME,
        settings.AUTH_PRESENCE_COOKIE_NAME,
        settings.AUTH_EXPIRES_COOKIE_NAME,
    ):
        response.delete_cookie(name, path="/", domain=_COOKIE_KWARGS["domain"])


def _extract_bearer_token(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid authorization header")
    return token.strip()


def _extract_token(request: Request, authorization: str | None) -> str:
    """从 Bearer header 或 HttpOnly cookie 提取 token。

    优先 Bearer header（API 客户端），回退到 cookie（浏览器）。
    """
    if authorization:
        return _extract_bearer_token(authorization)
    cookie_token = request.cookies.get(settings.AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authentication")


async def get_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User:
    token = _extract_token(request, authorization)
    user = await get_user_for_token(db, token)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user


async def get_optional_current_user(
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    if not authorization and not request.cookies.get(settings.AUTH_COOKIE_NAME):
        return None
    try:
        token = _extract_token(request, authorization)
    except HTTPException:
        return None
    return await get_user_for_token(db, token)


async def get_current_admin_user(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required") from None
    return current_user


def is_admin(user: User | None) -> bool:
    """Return True when *user* is non-null and holds the ``admin`` role.

    Shared by endpoints that need a non-Dependency admin check (e.g. optional
    auth + ``admin_view`` query flag). For strict admin-only endpoints prefer
    ``Depends(get_current_admin_user)``.
    """
    return bool(user and user.role == UserRole.ADMIN.value)


def require_admin_view(admin_view: bool, user: User | None) -> None:
    """Enforce the ``admin_view`` query flag contract.

    - ``admin_view=False`` → no-op (any caller, including anonymous).
    - ``admin_view=True`` without auth → 401.
    - ``admin_view=True`` with a non-admin user → 403.
    """
    if not admin_view:
        return
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing authorization header")
    if not is_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin privileges required")


@router.post(
    "/send-code",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(enforce_send_code_rate_limit)],
)
async def send_code(data: SendCodeRequest, request: Request, db: AsyncSession = Depends(get_db)):
    """发送邮箱验证码。注册前需先调用本接口获取验证码。

    频率限制：同 IP 每分钟最多 AUTH_SEND_CODE_ATTEMPTS_PER_MINUTE 次；
    同邮箱 60 秒内只能发送一次（由 service 层校验）。
    """
    try:
        await send_verification_code(db, data.email)
        logger.info("Send-code requested: email=%s, ip=%s", data.email, client_ip(request))
    except CodeRateLimitedError:
        logger.info("Send-code rate-limited: email=%s, ip=%s", data.email, client_ip(request))
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="验证码已发送，请稍后再试") from None
    except EmailNotConfiguredError:
        logger.warning("Send-code failed (email not configured): email=%s, ip=%s", data.email, client_ip(request))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="邮件服务尚未配置，请联系管理员"
        ) from None
    except VerificationError as exc:
        logger.warning("Send-code failed: email=%s, ip=%s, exc=%s", data.email, client_ip(request), exc)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.post(
    "/register",
    response_model=AuthTokenResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(enforce_register_rate_limit)],
)
async def register(
    data: AuthRegisterRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    existing = await get_user_by_email(db, data.email)
    if existing:
        logger.warning("Register failed (email exists): email=%s, ip=%s", data.email, ip)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    try:
        await verify_code(db, data.email, data.verification_code)
    except InvalidCodeError as exc:
        logger.warning("Register failed (invalid code): email=%s, ip=%s", data.email, ip)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        user = await create_user(db, email=data.email, password=data.password, display_name=data.display_name)
        token, session = await create_session(db, user)
    except IntegrityError:
        logger.warning("Register failed (integrity): email=%s, ip=%s", data.email, ip)
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered") from None

    _set_auth_cookies(response, token, session.expires_at)
    logger.info("Register success: email=%s, user_id=%d, ip=%s", data.email, user.id, ip)
    return AuthTokenResponse(access_token=token, expires_at=session.expires_at, user=UserResponse.model_validate(user))


@router.post("/login", response_model=AuthTokenResponse, dependencies=[Depends(enforce_login_rate_limit)])
async def login(
    data: AuthLoginRequest,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    ip = client_ip(request)
    user = await authenticate_user(db, email=data.email, password=data.password)
    if not user:
        logger.warning("Login failed: email=%s, ip=%s", data.email, ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
    token, session = await create_session(db, user)
    _set_auth_cookies(response, token, session.expires_at)
    logger.info("Login success: email=%s, user_id=%d, ip=%s", data.email, user.id, ip)
    return AuthTokenResponse(access_token=token, expires_at=session.expires_at, user=UserResponse.model_validate(user))


@router.get("/me", response_model=UserResponse)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post(
    "/refresh",
    response_model=AuthTokenResponse,
    dependencies=[Depends(enforce_refresh_rate_limit)],
)
async def refresh(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """续期当前 session。

    接受当前有效的 Bearer token 或 auth cookie，延长 session 过期时间，
    返回更新后的 expires_at。token 本身不变（不旋转），前端只需更新
    本地存储的 expires_at。

    如果 token 无效或已过期超过宽限期，返回 401。
    """
    token = _extract_token(request, authorization)
    result = await refresh_session(db, token)
    if result is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    user, session = result
    await db.commit()
    _set_auth_cookies(response, token, session.expires_at)
    logger.info("Session refreshed: user_id=%d, ip=%s", user.id, client_ip(request))
    return AuthTokenResponse(
        access_token=token,
        expires_at=session.expires_at,
        user=UserResponse.model_validate(user),
    )


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    token = _extract_token(request, authorization)
    ok = await revoke_token(db, token)
    _clear_auth_cookies(response)
    ip = client_ip(request)
    logger.info("Logout: ok=%s, ip=%s", ok, ip)
    return {"logged_out": True}


@router.post("/change-password")
async def change_my_password(
    data: ChangePasswordRequest,
    request: Request,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    """用户自助修改密码。

    校验旧密码后才允许修改；成功后撤销该用户其他设备的登录会话，
    当前调用方的 session 保留（keep_token）。
    """
    ip = client_ip(request)
    token = _extract_token(request, authorization)
    user = await get_user_for_token(db, token)
    if not user:
        logger.warning("Change-password failed (invalid token): ip=%s", ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")

    try:
        await change_password(db, user, data.old_password, data.new_password, keep_token=token)
    except ValueError as exc:
        logger.warning("Change-password failed: user_id=%d, ip=%s, reason=%s", user.id, ip, exc)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    await db.commit()
    logger.info("Change-password success: user_id=%d, ip=%s", user.id, ip)
    return {"message": "密码修改成功，其他设备的登录状态已失效"}
