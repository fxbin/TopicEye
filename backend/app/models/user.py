from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True, index=True)
    # nullable: 纯 OAuth 用户（Google/GitHub 登录）没有密码
    password_hash: Mapped[str | None] = mapped_column(String(512), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    plan: Mapped[str] = mapped_column(String(20), nullable=False, default="free")
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    sessions: Mapped[list[UserSession]] = relationship(back_populates="user", cascade="all, delete-orphan")
    api_tokens: Mapped[list[UserApiToken]] = relationship(back_populates="user", cascade="all, delete-orphan")
    oauth_accounts: Mapped[list[UserOAuthAccount]] = relationship(back_populates="user", cascade="all, delete-orphan")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    user: Mapped[User] = relationship(back_populates="sessions")

    __table_args__ = (
        Index("ix_user_sessions_user_expires", "user_id", "expires_at"),
        Index("ix_user_sessions_token_active", "token_hash", "revoked_at"),
    )


class UserApiToken(Base):
    """用户的个人 API access token（用于脚本/CI 调 API）。

    与 UserSession 区别：
    - Session: 浏览器登录会话（短期 30 天，每次刷新续期）
    - ApiToken: 长期 access token（脚本场景），支持命名 / 撤销 / 过期
    """

    __tablename__ = "user_api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="用户可读的名字，如 'CI 脚本'")
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # SHA-256 prefix 前 8 位用于在 UI 上识别（不暴露完整 hash）
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    user: Mapped[User] = relationship(back_populates="api_tokens")

    __table_args__ = (
        Index("ix_user_api_tokens_user_active", "user_id", "revoked_at"),
        Index("ix_user_api_tokens_token_active", "token_hash", "revoked_at"),
    )


class UserOAuthAccount(Base):
    """第三方 OAuth 身份（Google / GitHub）与本地 User 的关联。

    一个 provider 用户只能关联一个本地账号（provider + provider_user_id 唯一）。
    首次 OAuth 登录时，若 provider 声明邮箱已验证且与现有账号邮箱相同，自动合并。
    """

    __tablename__ = "user_oauth_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    provider: Mapped[str] = mapped_column(String(20), nullable=False)
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[str] = mapped_column(String(255), nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    display_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    user: Mapped[User] = relationship(back_populates="oauth_accounts")

    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_user_oauth_accounts_provider_user"),
        Index("ix_user_oauth_accounts_provider_email", "provider", "provider_email"),
        Index("ix_user_oauth_accounts_user_id", "user_id"),
    )
