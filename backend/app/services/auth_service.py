from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sqlite_retry import retry_sqlite_locked
from app.models.user import User, UserApiToken, UserOAuthAccount, UserSession

_HASH_ALGORITHM = "pbkdf2_sha256"
_HASH_ITERATIONS = 260_000
_SALT_BYTES = 16
_SESSION_TOKEN_BYTES = 32


def normalize_email(email: str) -> str:
    return email.strip().lower()


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _HASH_ITERATIONS)
    return "$".join(
        [
            _HASH_ALGORITHM,
            str(_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, password_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = password_hash.split("$", 3)
        if algorithm != _HASH_ALGORITHM:
            return False
        iterations = int(iterations_raw)
        salt = base64.urlsafe_b64decode(salt_raw.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def new_session_token() -> str:
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    result = await db.execute(select(User).where(User.email == normalize_email(email)))
    return result.scalar_one_or_none()


async def create_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
    role: str = "user",
) -> User:
    user = User(
        email=normalize_email(email),
        password_hash=hash_password(password),
        display_name=display_name or normalize_email(email).split("@", 1)[0],
        role=role,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


class OAuthAccountConflictError(Exception):
    """OAuth 登录时邮箱与现有账号冲突但无法自动合并。

    典型场景：provider 声明的邮箱未验证，但该邮箱已被本地密码账号占用。
    拒绝自动合并以防账号劫持，提示用户先用密码登录后在设置页手动绑定。
    """


async def get_oauth_account(
    db: AsyncSession, *, provider: str, provider_user_id: str
) -> UserOAuthAccount | None:
    result = await db.execute(
        select(UserOAuthAccount).where(
            UserOAuthAccount.provider == provider,
            UserOAuthAccount.provider_user_id == provider_user_id,
        )
    )
    return result.scalar_one_or_none()


async def get_or_create_oauth_user(
    db: AsyncSession,
    *,
    provider: str,
    provider_user_id: str,
    email: str,
    email_verified: bool,
    display_name: str | None = None,
) -> User:
    """解析 OAuth 身份为本地 User，自动关联合并同邮箱账号。

    合并策略（见 plan）：
    1. (provider, provider_user_id) 已绑定 → 直接返回关联 User
    2. 未绑定 + email_verified=True + email 命中现有账号 → 新建 oauth_account 挂上去
    3. 未绑定 + email_verified=False + email 命中现有账号 → 抛 OAuthAccountConflictError（防劫持）
    4. 都没命中 → 创建新 User（无密码）+ oauth_account
    """
    normalized = normalize_email(email)

    # 1. 已绑定的 provider 用户
    existing = await get_oauth_account(db, provider=provider, provider_user_id=provider_user_id)
    if existing:
        user = await db.get(User, existing.user_id)
        if user and user.is_active:
            return user
        if user:
            raise OAuthAccountConflictError("绑定的账号已被停用，请联系管理员")
        # 绑定记录存在但用户不存在（理论上有 CASCADE 不该发生），清理僵尸记录
        await db.delete(existing)
        await db.flush()

    # 检查邮箱是否已被现有账号占用
    existing_user = await get_user_by_email(db, normalized)

    # 2 & 3. 邮箱冲突时的合并 / 拒绝
    if existing_user:
        if not email_verified:
            raise OAuthAccountConflictError(
                "该邮箱已注册但 OAuth 邮箱未验证，请先用密码登录后在设置页绑定第三方账号"
            )
        # 已验证 → 自动合并：把 oauth_account 挂到现有账号
        await _link_oauth_account(
            db,
            user_id=existing_user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=normalized,
            email_verified=email_verified,
            display_name=display_name,
        )
        return existing_user

    # 4. 全新用户
    fallback_name = display_name or normalized.split("@", 1)[0]

    async def _create_oauth_only_user() -> User:
        user = User(
            email=normalized,
            password_hash=None,
            display_name=fallback_name,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        await _link_oauth_account(
            db,
            user_id=user.id,
            provider=provider,
            provider_user_id=provider_user_id,
            provider_email=normalized,
            email_verified=email_verified,
            display_name=display_name,
        )
        return user

    return await retry_sqlite_locked(_create_oauth_only_user, on_retry=db.rollback)


async def _link_oauth_account(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    provider_user_id: str,
    provider_email: str,
    email_verified: bool,
    display_name: str | None,
) -> UserOAuthAccount:
    """新建一条 user_oauth_accounts 记录（已假设 (provider, provider_user_id) 未占用）。"""
    account = UserOAuthAccount(
        user_id=user_id,
        provider=provider,
        provider_user_id=str(provider_user_id),
        provider_email=provider_email,
        email_verified=email_verified,
        display_name=display_name,
    )
    db.add(account)
    await db.flush()
    await db.refresh(account)
    return account


async def ensure_admin_user(
    db: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    user = await get_user_by_email(db, email)
    if not user:
        return await create_user(
            db,
            email=email,
            password=password,
            display_name=display_name,
            role="admin",
        )

    changed = False
    if user.password_hash == "__seeded_after_startup__":
        user.password_hash = hash_password(password)
        changed = True
    if user.role != "admin":
        user.role = "admin"
        changed = True
    if not user.is_active:
        user.is_active = True
        changed = True
    if display_name and not user.display_name:
        user.display_name = display_name
        changed = True
    if changed:
        user.updated_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, *, email: str, password: str) -> User | None:
    user = await get_user_by_email(db, email)
    if not user or not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None
    return user


async def create_session(db: AsyncSession, user: User, *, days: int = 30) -> tuple[str, UserSession]:
    token = new_session_token()
    session = UserSession(
        user_id=user.id,
        token_hash=hash_token(token),
        expires_at=datetime.now(UTC) + timedelta(days=days),
    )

    async def insert_session() -> UserSession:
        db.add(session)
        await db.flush()
        await db.refresh(session)
        return session

    await retry_sqlite_locked(insert_session, on_retry=db.rollback)
    return token, session


async def get_user_for_token(db: AsyncSession, token: str) -> User | None:
    """Resolve a Bearer token to a User. Tries UserSession first, then UserApiToken."""
    now = datetime.now(UTC)
    token_h = hash_token(token)

    # 1. Try session token (浏览器登录会话)
    result = await db.execute(
        select(UserSession.id, User.id)
        .join(User, User.id == UserSession.user_id)
        .where(
            UserSession.token_hash == token_h,
            UserSession.revoked_at.is_(None),
            UserSession.expires_at > now,
            User.is_active.is_(True),
        )
    )
    row = result.first()
    if row:
        _, user_id = row
        return await db.get(User, user_id)

    # 2. Fallback to API token (脚本/CI 场景)
    api_result = await db.execute(
        select(UserApiToken.id, UserApiToken.user_id)
        .join(User, User.id == UserApiToken.user_id)
        .where(
            UserApiToken.token_hash == token_h,
            UserApiToken.revoked_at.is_(None),
            User.is_active.is_(True),
        )
    )
    api_row = api_result.first()
    if not api_row:
        return None
    # 过期检查（API token 可选过期）
    token_id, user_id = api_row
    api_token = await db.get(UserApiToken, token_id)
    if api_token and api_token.expires_at and api_token.expires_at <= now:
        return None
    # 更新 last_used_at（best-effort，失败不阻塞）
    if api_token:
        try:
            api_token.last_used_at = now
            await db.flush()
        except Exception:
            await db.rollback()
    return await db.get(User, user_id)


async def revoke_token(db: AsyncSession, token: str) -> bool:
    result = await db.execute(
        select(UserSession).where(
            UserSession.token_hash == hash_token(token),
            UserSession.revoked_at.is_(None),
        )
    )
    session = result.scalar_one_or_none()
    if not session:
        return False
    session.revoked_at = datetime.now(UTC)
    await db.flush()
    return True


async def revoke_all_user_sessions(db: AsyncSession, user_id: int, *, keep_token: str | None = None) -> int:
    """撤销该用户所有未过期的活跃 session。

    用于管理员重置密码 / 用户自助改密后强制其他设备下线。
    keep_token 指定时，保留当前调用方的 session（自助改密场景保留自己）。

    返回被撤销的 session 数（flush 后即生效，调用方负责 commit）。
    """
    conditions = [
        UserSession.user_id == user_id,
        UserSession.revoked_at.is_(None),
    ]
    if keep_token is not None:
        conditions.append(UserSession.token_hash != hash_token(keep_token))
    result = await db.execute(
        update(UserSession).where(*conditions).values(revoked_at=datetime.now(UTC))
    )
    return int(result.rowcount or 0)


async def change_password(
    db: AsyncSession,
    user: User,
    old_password: str,
    new_password: str,
    *,
    keep_token: str | None = None,
) -> None:
    """用户自助改密：校验旧密码 → 写新密码 → 撤销其他 session。

    旧密码校验失败抛 ValueError，由调用方转 400。
    """
    if not user.password_hash or not verify_password(old_password, user.password_hash):
        raise ValueError("旧密码不正确")
    # 留给 endpoint 层做 schema 级强度校验，这里防御性兜底
    if len(new_password) < 8:
        raise ValueError("新密码至少 8 位")
    user.password_hash = hash_password(new_password)
    await db.flush()
    await revoke_all_user_sessions(db, user.id, keep_token=keep_token)


# ── User API tokens (脚本/CI 场景) ───────────────────────────────────

_API_TOKEN_BYTES = 32  # 256-bit raw → urlsafe base64 ≈ 43 chars


def new_api_token() -> str:
    """生成一个新的随机 API token (urlsafe)。"""
    return secrets.token_urlsafe(_API_TOKEN_BYTES)


async def create_api_token(
    db: AsyncSession,
    *,
    user_id: int,
    name: str,
    expires_at: datetime | None = None,
) -> tuple[str, UserApiToken]:
    """创建一个 API token。返回 (明文 token, record)。

    明文 token 只在创建时返回一次，后续无法恢复（只存 hash）。
    """
    raw = new_api_token()
    record = UserApiToken(
        user_id=user_id,
        name=name[:100],
        token_hash=hash_token(raw),
        token_prefix=hash_token(raw)[:8],
        expires_at=expires_at,
    )
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return raw, record


async def list_api_tokens(db: AsyncSession, user_id: int) -> list[UserApiToken]:
    """列出该用户所有 API token（含已撤销，按创建时间倒序）。"""
    result = await db.execute(
        select(UserApiToken).where(UserApiToken.user_id == user_id).order_by(UserApiToken.created_at.desc())
    )
    return list(result.scalars().all())


async def revoke_api_token(db: AsyncSession, *, user_id: int, token_id: int) -> bool:
    """撤销指定 API token（per-user 校验：只能撤自己的）。"""
    result = await db.execute(
        select(UserApiToken).where(
            UserApiToken.id == token_id,
            UserApiToken.user_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record or record.revoked_at is not None:
        return False
    record.revoked_at = datetime.now(UTC)
    await db.flush()
    return True


async def delete_api_token(db: AsyncSession, *, user_id: int, token_id: int) -> bool:
    """删除指定 API token（per-user 校验）。"""
    result = await db.execute(
        select(UserApiToken).where(
            UserApiToken.id == token_id,
            UserApiToken.user_id == user_id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        return False
    await db.delete(record)
    await db.flush()
    return True
