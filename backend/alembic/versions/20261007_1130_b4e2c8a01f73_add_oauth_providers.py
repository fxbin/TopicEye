"""第三方登录凭据入 DB：oauth_providers 表 + env 一次性导入

Revision ID: b4e2c8a01f73
Revises: d8f3b6a21c70
Create Date: 2026-10-07

#94 起 OAuth provider 凭据（google / github）改为管理后台配置、DB 单一事实源：

- oauth_providers 表：provider 主键 + client_id + client_secret（Fernet 密文）+ enabled
- 升级时把旧 .env / 环境变量里的 OAUTH_GOOGLE_*/OAUTH_GITHUB_* 一次性导入
  （两端都齐全才导入并启用；此后 .env 里的旧变量失效，可删除）
- 注意：生产环境若未配置 INTEGRATION_SECRET_KEY（或自定义 APP_SECRET_KEY），
  encrypt_secret 会抛 RuntimeError——这是既有的 fail-closed 约束（与 LLM api_key、
  邮件密码同一把钥匙），升级前先确认该变量已设置。

env 读取不走 pydantic Settings（字段已随 #94 删除），直接 os.environ 优先、
backend/.env 兜底，避免迁移依赖已不存在的配置声明。
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import sqlalchemy as sa

from alembic import op

revision: str = "b4e2c8a01f73"
down_revision: str | None = "d8f3b6a21c70"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 迁移文件位于 backend/alembic/versions/，backend 目录即 .env 所在处
_BACKEND_DIR = Path(__file__).resolve().parents[2]

# 旧 env 变量名 → provider 名（凭据成对齐全才导入）
_LEGACY_ENV_VARS: dict[str, tuple[str, str]] = {
    "google": ("OAUTH_GOOGLE_CLIENT_ID", "OAUTH_GOOGLE_CLIENT_SECRET"),
    "github": ("OAUTH_GITHUB_CLIENT_ID", "OAUTH_GITHUB_CLIENT_SECRET"),
}


def _legacy_env_value(name: str) -> str:
    """读旧配置：真实环境变量优先，backend/.env 兜底（本地开发场景）。"""
    value = os.environ.get(name)
    if value is None:
        try:
            from dotenv import dotenv_values

            value = dotenv_values(_BACKEND_DIR / ".env").get(name)
        except Exception:
            value = None
    return (value or "").strip()


def upgrade() -> None:
    op.create_table(
        "oauth_providers",
        sa.Column("provider", sa.String(length=32), primary_key=True),
        sa.Column("client_id", sa.String(length=512), nullable=True),
        sa.Column("client_secret", sa.Text(), nullable=True, comment="Fernet 密文，enc:v1: 前缀"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # 一次性导入旧 env 凭据（导入后 .env 里的旧变量即可删除）
    from app.services.secret_store import encrypt_secret

    rows = []
    for provider, (id_var, secret_var) in _LEGACY_ENV_VARS.items():
        client_id = _legacy_env_value(id_var)
        client_secret = _legacy_env_value(secret_var)
        if client_id and client_secret:
            rows.append(
                {
                    "provider": provider,
                    "client_id": client_id,
                    "client_secret": encrypt_secret(client_secret),
                    "enabled": True,
                    "updated_at": datetime.now(UTC),
                }
            )
    if rows:
        op.bulk_insert(
            sa.table(
                "oauth_providers",
                sa.Column("provider", sa.String),
                sa.Column("client_id", sa.String),
                sa.Column("client_secret", sa.Text),
                sa.Column("enabled", sa.Boolean),
                sa.Column("updated_at", sa.DateTime),
            ),
            rows,
        )


def downgrade() -> None:
    # 回滚会丢弃后台配置的凭据（表内无其他数据依赖）；需要保留时先 pg_dump
    op.drop_table("oauth_providers")
