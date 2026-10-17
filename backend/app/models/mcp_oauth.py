"""MCP OAuth 授权服务器存储 — 动态客户端注册 / 授权码 / token。

TopicEye 作为 OAuth 2.1 授权服务器（AS）支撑 MCP `/mcp` 资源服务器（RS）的
浏览器弹窗登录。三张表均属 Postgres 事务层：

- ``mcp_oauth_clients``：RFC 7591 动态注册的客户端；secret 以 Fernet 密文
  存储（同 oauth_providers 先例），完整元数据以 JSON 存 metadata_json。
- ``mcp_oauth_authorizations``：一表承载两种状态——``/authorize`` 落的
  pending 授权请求（发给前端同意页 request_id），用户批准后同一行盖上
  ``code_hash`` 变成一次性授权码（status: pending/approved/denied/consumed）。
- ``mcp_oauth_tokens``：access / refresh 共表（token_type 区分），raw token
  只回传客户端一次，库存 sha256（与 user_sessions / user_api_tokens 同模式）；
  ``family_id`` 串起轮换链，refresh 重放检测按 family 整体撤销。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MCPOAuthClient(Base):
    """通过 DCR（POST /register）注册的 MCP 客户端。"""

    __tablename__ = "mcp_oauth_clients"
    __table_args__ = (Index("ix_mcp_oauth_clients_client_id", "client_id", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    client_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="SDK 注册时生成的 uuid4")
    client_name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="同意页展示的应用名")
    client_secret_enc: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="Fernet 密文（enc:v1:）；公共客户端（method=none）为 NULL"
    )
    metadata_json: Mapped[str] = mapped_column(
        Text, nullable=False, comment="OAuthClientInformationFull dump（不含 secret）"
    )
    registered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MCPOAuthAuthorization(Base):
    """/authorize 授权请求 →（批准后）一次性授权码，同一行两种身份。"""

    __tablename__ = "mcp_oauth_authorizations"
    __table_args__ = (
        Index("ix_mcp_oauth_authorizations_request_id", "request_id", unique=True),
        Index("ix_mcp_oauth_authorizations_code_hash", "code_hash", unique=True),
        Index("ix_mcp_oauth_authorizations_client_status", "client_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="uuid4，发给前端同意页")
    status: Mapped[str] = mapped_column(
        String(12), default="pending", nullable=False, comment="pending / approved / denied / consumed"
    )
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="批准时生成的授权码 sha256")
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON 数组")
    state: Mapped[str | None] = mapped_column(Text, nullable=True, comment="客户端 state 原样带回")
    code_challenge: Mapped[str] = mapped_column(String(128), nullable=False, comment="PKCE S256 challenge")
    redirect_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    resource: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="RFC 8707 资源指示符")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )


class MCPOAuthToken(Base):
    """OAuth access / refresh token（不透明 token，库存 sha256）。"""

    __tablename__ = "mcp_oauth_tokens"
    __table_args__ = (
        Index("ix_mcp_oauth_tokens_token_hash", "token_hash", unique=True),
        Index("ix_mcp_oauth_tokens_family", "family_id"),
        Index("ix_mcp_oauth_tokens_client_type", "client_id", "token_type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="sha256 hex")
    token_type: Mapped[str] = mapped_column(String(10), nullable=False, comment="access / refresh")
    client_id: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    family_id: Mapped[str] = mapped_column(String(36), nullable=False, comment="授权码发放起的轮换链标识")
    scopes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON 数组")
    resource: Mapped[str | None] = mapped_column(String(512), nullable=True, comment="RFC 8707 资源指示符")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
