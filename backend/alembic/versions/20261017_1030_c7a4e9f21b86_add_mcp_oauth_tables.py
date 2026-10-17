"""MCP 动态 OAuth 授权服务器存储：三张表

Revision ID: c7a4e9f21b86
Revises: b4e2c8a01f73
Create Date: 2026-10-17

#116 起 MCP server 支持标准 OAuth 2.1 浏览器弹窗登录（授权码 + PKCE +
DCR），需要授权服务器侧的持久化：

- mcp_oauth_clients：RFC 7591 动态注册的客户端（secret 为 Fernet 密文，
  同 oauth_providers 先例，依赖 INTEGRATION_SECRET_KEY 已配置）
- mcp_oauth_authorizations：/authorize 落的 pending 授权请求，用户批准后
  同一行盖 code_hash 变一次性授权码（pending/approved/denied/consumed）
- mcp_oauth_tokens：access / refresh 共表，库存 sha256（raw 只回传一次），
  family_id 串起轮换链供重放检测整族撤销

新表全部为增量（无数据回填、不改既有表），downgrade 直接删表；若生产
已有用户完成过 OAuth 授权，回滚前先备份 token 行。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c7a4e9f21b86"
down_revision: str | None = "b4e2c8a01f73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mcp_oauth_clients",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("client_id", sa.String(length=64), nullable=False, comment="SDK 注册时生成的 uuid4"),
        sa.Column("client_name", sa.String(length=200), nullable=True, comment="同意页展示的应用名"),
        sa.Column(
            "client_secret_enc",
            sa.Text(),
            nullable=True,
            comment="Fernet 密文（enc:v1:）；公共客户端（method=none）为 NULL",
        ),
        sa.Column(
            "metadata_json",
            sa.Text(),
            nullable=False,
            comment="OAuthClientInformationFull dump（不含 secret）",
        ),
        sa.Column("registered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_mcp_oauth_clients_client_id", "mcp_oauth_clients", ["client_id"], unique=True)

    op.create_table(
        "mcp_oauth_authorizations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("request_id", sa.String(length=36), nullable=False, comment="uuid4，发给前端同意页"),
        sa.Column(
            "status",
            sa.String(length=12),
            nullable=False,
            server_default="pending",
            comment="pending / approved / denied / consumed",
        ),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("code_hash", sa.String(length=64), nullable=True, comment="批准时生成的授权码 sha256"),
        sa.Column("scopes", sa.Text(), nullable=True, comment="JSON 数组"),
        sa.Column("state", sa.Text(), nullable=True, comment="客户端 state 原样带回"),
        sa.Column("code_challenge", sa.String(length=128), nullable=False, comment="PKCE S256 challenge"),
        sa.Column("redirect_uri", sa.String(length=512), nullable=False),
        sa.Column("redirect_uri_provided_explicitly", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("resource", sa.String(length=512), nullable=True, comment="RFC 8707 资源指示符"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_mcp_oauth_authorizations_request_id", "mcp_oauth_authorizations", ["request_id"], unique=True)
    op.create_index("ix_mcp_oauth_authorizations_code_hash", "mcp_oauth_authorizations", ["code_hash"], unique=True)
    op.create_index("ix_mcp_oauth_authorizations_client_status", "mcp_oauth_authorizations", ["client_id", "status"])

    op.create_table(
        "mcp_oauth_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False, comment="sha256 hex"),
        sa.Column("token_type", sa.String(length=10), nullable=False, comment="access / refresh"),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("family_id", sa.String(length=36), nullable=False, comment="授权码发放起的轮换链标识"),
        sa.Column("scopes", sa.Text(), nullable=True, comment="JSON 数组"),
        sa.Column("resource", sa.String(length=512), nullable=True, comment="RFC 8707 资源指示符"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_mcp_oauth_tokens_token_hash", "mcp_oauth_tokens", ["token_hash"], unique=True)
    op.create_index("ix_mcp_oauth_tokens_family", "mcp_oauth_tokens", ["family_id"])
    op.create_index("ix_mcp_oauth_tokens_client_type", "mcp_oauth_tokens", ["client_id", "token_type"])


def downgrade() -> None:
    # 回滚丢弃 OAuth 客户端注册与 token（存量静态 token 不受影响）；
    # 需要保留授权历史时先 pg_dump 这三张表
    op.drop_table("mcp_oauth_tokens")
    op.drop_table("mcp_oauth_authorizations")
    op.drop_table("mcp_oauth_clients")
