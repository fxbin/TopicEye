"""weread stats cache table

Revision ID: 7e8f9a0b1c2d
Revises: 9d0e1f2a3b4c
Create Date: 2026-07-20 10:30:00.000000

新建 weread_stats_cache 表，缓存微信读书阅读统计和书架对比数据。
每日凌晨 05:00 由 scheduler 定时刷新，API 层优先读缓存以加速响应。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "7e8f9a0b1c2d"
down_revision = "9d0e1f2a3b4c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weread_stats_cache",
        sa.Column("id", sa.Integer(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("cache_type", sa.String(length=20), nullable=False, comment="readdata / shelf"),
        sa.Column("read_type", sa.String(length=10), nullable=False, server_default="all",
                   comment="all/week/month/year for readdata; 'all' for shelf"),
        sa.Column("payload", sa.JSON(), nullable=False, comment="Full API response payload"),
        sa.Column("error", sa.Text(), nullable=True, comment="Error message if fetch failed"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                   server_default=sa.text("(CURRENT_TIMESTAMP)")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "cache_type", "read_type",
                             name="uq_weread_cache_user_type_period"),
    )
    with op.batch_alter_table("weread_stats_cache", schema=None) as batch_op:
        batch_op.create_index("ix_weread_cache_user_type", ["user_id", "cache_type"])


def downgrade() -> None:
    op.drop_table("weread_stats_cache")
