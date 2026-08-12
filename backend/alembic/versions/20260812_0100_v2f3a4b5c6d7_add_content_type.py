"""add content_type column to content_items for dual-axis classification

Revision ID: v2f3a4b5c6d7
Revises: u1f2a3b4c5d6
Create Date: 2026-08-12 01:00:00

新增 content_type 列，实现双轴分类：
  - category: 主题轴（AI / 科技 / 产品 / ...）
  - content_type: 形态轴（论文 / 技术 / 资讯 / 教程 / ...）

数据回填策略：
  1. 从 source.category 的 `/` 分隔符解析（如 "AI/论文" -> content_type="论文"）
  2. arXiv 平台硬规则回填 content_type="论文"

纯增量操作：加列 + 加索引 + 数据回填，无删除/变更已有列。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "v2f3a4b5c6d7"
down_revision = "u1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("content_type", sa.String(50), nullable=True),
    )

    # ── Backfill 1: 从 source.category 的 `/` 分隔符解析 ──────────────
    # 使用 Python 逐行回填，兼容 PostgreSQL 和 SQLite
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, category FROM sources WHERE category LIKE '%/%'")
    ).fetchall()
    for source_id, category in rows:
        parts = str(category).split("/", 1)
        if len(parts) == 2:
            content_type = parts[1].strip()
            if content_type:
                conn.execute(
                    sa.text(
                        "UPDATE content_items SET content_type = :ct "
                        "WHERE source_id = :sid AND content_type IS NULL"
                    ),
                    {"ct": content_type, "sid": source_id},
                )

    # ── Backfill 2: arXiv 平台硬规则 ──────────────────────────────────
    conn.execute(
        sa.text(
            "UPDATE content_items SET content_type = '论文' "
            "WHERE platform = 'arXiv' AND content_type IS NULL"
        )
    )

    op.create_index(
        "ix_content_items_content_type",
        "content_items",
        ["content_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_content_type", table_name="content_items")
    op.drop_column("content_items", "content_type")
