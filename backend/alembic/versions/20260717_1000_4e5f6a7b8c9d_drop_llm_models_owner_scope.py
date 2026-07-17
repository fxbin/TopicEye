"""drop llm_models.owner_user_id and scope columns

Revision ID: 4e5f6a7b8c9d
Revises: 3d4e5f6a7b8c
Create Date: 2026-07-17 10:00:00

用户自定义 AI（BYOK）功能已整体移除，per-user 模型路由不再使用。
owner_user_id（及外键）和 scope 两个字段以及 ix_llm_models_owner_route
索引随之删除，避免遗留 schema 造成后期兼容性歧义。

llm_models 表此后只承载系统级模型配置。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "4e5f6a7b8c9d"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite 需要 batch_alter_table 才能 drop 列 / 约束；batch 模式重建表时会
    # 自动丢弃被删列上的外键约束，故无需显式 drop_constraint。Postgres/MySQL 同样兼容。
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.drop_index("ix_llm_models_owner_route")
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.drop_column("owner_user_id")
        batch_op.drop_column("scope")


def downgrade() -> None:
    # 恢复 BYOK 时代的 schema。scope 重建为 NOT NULL DEFAULT 'system'，
    # owner_user_id 重建为 nullable + 指向 users 的外键。
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.add_column(sa.Column("owner_user_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("scope", sa.String(length=20), nullable=False, server_default="system")
        )
        batch_op.create_foreign_key(
            "fk_llm_models_owner_user_id_users",
            "users",
            ["owner_user_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("llm_models", schema=None) as batch_op:
        batch_op.create_index(
            "ix_llm_models_owner_route",
            ["owner_user_id", "routing_group", "routing_priority"],
            unique=False,
        )
