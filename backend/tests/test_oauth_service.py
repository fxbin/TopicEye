"""OAuth 登录 service 层单测：get_or_create_oauth_user 的 4 个分支。

覆盖：
1. 已绑定的 provider 用户 → 直接返回关联 User（最常见路径）
2. 未绑定 + email_verified=True + email 命中现有密码账号 → 自动合并（新建 oauth_account 挂上去）
3. 未绑定 + email_verified=False + email 命中现有账号 → 抛 OAuthAccountConflictError（防劫持）
4. 全新邮箱 → 创建新 User（password_hash=None）+ oauth_account
"""

from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.user import UserOAuthAccount
from app.services.auth_service import (
    OAuthAccountConflictError,
    create_user,
    get_oauth_account,
    get_or_create_oauth_user,
)


async def _new_engine_with_schema():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest.mark.asyncio
async def test_oauth_returns_existing_linked_user():
    """分支 1：已绑定的 provider 用户直接登录。"""
    engine = await _new_engine_with_schema()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        user = await get_or_create_oauth_user(
            db,
            provider="github",
            provider_user_id="1001",
            email="linked@example.com",
            email_verified=True,
            display_name="Linked",
        )
        await db.commit()

        # 第二次同 provider+id 登录 → 应返回同一个 user
        again = await get_or_create_oauth_user(
            db,
            provider="github",
            provider_user_id="1001",
            email="linked@example.com",
            email_verified=True,
            display_name="Linked",
        )
        assert again.id == user.id
        # 不应新建第二条 oauth_account
        accounts = await db.execute(select(UserOAuthAccount).where(UserOAuthAccount.user_id == user.id))
        assert len(accounts.scalars().all()) == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_oauth_auto_merges_verified_email_to_password_account():
    """分支 2：已验证邮箱 + email 命中现有密码账号 → 自动合并。"""
    engine = await _new_engine_with_schema()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        # 先建一个密码账号
        pwd_user = await create_user(db, email="merge@Example.com", password="Password123", display_name="PwdUser")
        await db.flush()

        # Google 登录同邮箱（已验证）→ 应合并到 pwd_user
        oauth_user = await get_or_create_oauth_user(
            db,
            provider="google",
            provider_user_id="g-2002",
            email="merge@example.com",
            email_verified=True,
            display_name="GoogleUser",
        )
        await db.commit()

        assert oauth_user.id == pwd_user.id
        # oauth_account 应挂在 pwd_user 上
        account = await get_oauth_account(db, provider="google", provider_user_id="g-2002")
        assert account is not None
        assert account.user_id == pwd_user.id
        assert account.email_verified is True

    await engine.dispose()


@pytest.mark.asyncio
async def test_oauth_rejects_unverified_email_conflict():
    """分支 3：未验证邮箱 + email 命中现有账号 → 抛 OAuthAccountConflictError（防劫持）。"""
    engine = await _new_engine_with_schema()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        await create_user(db, email="hijack@example.com", password="Password123")
        await db.flush()

        # GitHub 登录同邮箱但 email_verified=False → 必须拒绝
        with pytest.raises(OAuthAccountConflictError):
            await get_or_create_oauth_user(
                db,
                provider="github",
                provider_user_id="gh-3003",
                email="hijack@example.com",
                email_verified=False,
                display_name="Attacker",
            )

    await engine.dispose()


@pytest.mark.asyncio
async def test_oauth_creates_new_passwordless_user():
    """分支 4：全新邮箱 → 创建无密码用户。"""
    engine = await _new_engine_with_schema()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        user = await get_or_create_oauth_user(
            db,
            provider="github",
            provider_user_id="gh-4004",
            email="brandnew@example.com",
            email_verified=True,
            display_name="BrandNew",
        )
        await db.commit()

        assert user.id is not None
        assert user.email == "brandnew@example.com"
        assert user.password_hash is None  # OAuth-only 用户无密码
        assert user.display_name == "BrandNew"
        assert user.role == "user"

        account = await get_oauth_account(db, provider="github", provider_user_id="gh-4004")
        assert account is not None
        assert account.user_id == user.id

    await engine.dispose()


@pytest.mark.asyncio
async def test_oauth_different_providers_same_verified_email_merge_into_one_account():
    """边界：同已验证邮箱、不同 provider → 第二次登录会按 email 命中合并到同一账号。

    这是「自动合并」策略的合理外延：已验证邮箱视为同一自然人的强信号，
    所以 Google 首次登录建账号后，GitHub 用同已验证邮箱登录应合并到同一账号，
    并把两条 oauth_account 都挂上去（一个账号可绑多个 provider）。
    """
    engine = await _new_engine_with_schema()
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        google_user = await get_or_create_oauth_user(
            db,
            provider="google",
            provider_user_id="g-5005",
            email="dual@example.com",
            email_verified=True,
            display_name="Dual Google",
        )
        github_user = await get_or_create_oauth_user(
            db,
            provider="github",
            provider_user_id="gh-5005",
            email="dual@example.com",
            email_verified=True,
            display_name="Dual GitHub",
        )
        await db.commit()

        # 同已验证邮箱 → 合并到同一账号
        assert google_user.id == github_user.id
        assert google_user.email == github_user.email == "dual@example.com"

        # 两条 oauth_account 都挂在该账号下（不同 provider）
        accounts = await db.execute(select(UserOAuthAccount).where(UserOAuthAccount.user_id == google_user.id))
        provider_set = {a.provider for a in accounts.scalars().all()}
        assert provider_set == {"google", "github"}

    await engine.dispose()
