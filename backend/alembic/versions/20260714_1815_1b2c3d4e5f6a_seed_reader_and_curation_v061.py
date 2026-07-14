"""seed reader and curation release v0.6.1

Revision ID: 1b2c3d4e5f6a
Revises: 0a1b2c3d4e5f
Create Date: 2026-07-14 18:15:00
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "1b2c3d4e5f6a"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


_VERSION = "v0.6.1"
_ITEMS = [
    {
        "title": "站内原文阅读",
        "description": "内容卡片现可进入站内阅读：优先使用已采集正文，否则按安全边界读取公开网页；始终保留来源跳转，不渲染第三方 HTML。",
        "kind": "release",
    },
    {
        "title": "长文阅读排版优化",
        "description": "正文快照保留标题、段落、引用和列表；阅读页改为单一阅读纸与更舒适的行长、行距，旧快照也会自动切段。",
        "kind": "improvement",
    },
    {
        "title": "精选可见性与缓存口径修正",
        "description": "精选、低粉爆文和内容列表统一遵循公共内容加本人私有内容的可见性范围，并按用户隔离相关缓存。",
        "kind": "fix",
    },
    {
        "title": "站内阅读结果观测",
        "description": "记录读取成功、缓存命中、失败原因与耗时，为后续只向高价值来源引入 JS 渲染能力提供数据依据。",
        "kind": "improvement",
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT id FROM product_updates WHERE version = :version"),
        {"version": _VERSION},
    ).fetchone()
    if exists is not None:
        return

    now_sql = "CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "NOW()"
    items_sql = ":items" if bind.dialect.name == "sqlite" else "CAST(:items AS JSON)"
    bind.execute(
        sa.text(
            f"""
            INSERT INTO product_updates (version, status, shipped_at, items, created_at, updated_at)
            VALUES (:version, :status, {now_sql}, {items_sql}, {now_sql}, {now_sql})
            """
        ),
        {
            "version": _VERSION,
            "status": "shipped",
            "items": json.dumps(_ITEMS, ensure_ascii=False),
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM product_updates WHERE version = :version"), {"version": _VERSION})
