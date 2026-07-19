"""seed release v0.8.0

Revision ID: 7b8c9d0e1f2a
Revises: 6a7b8c9d0e1f
Create Date: 2026-07-19 11:00:00.000000

发布 v0.8.0：母题 per-user 化（系统模板库 + 用户 fork 模式）。
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "7b8c9d0e1f2a"
down_revision = "6a7b8c9d0e1f"
branch_labels = None
depends_on = None


_VERSION = "v0.8.0"
_ITEMS = [
    {
        "title": "母题 per-user 化：系统模板库 + 用户 fork",
        "description": "母题从全局共享改为多租户模型。admin 维护系统模板库（owner_user_id IS NULL，所有用户只读）；普通用户首次访问「我的母题」时自动 fork 一份系统模板到自己名下，之后可自由调整关键词、权重和目标读者，改动立即影响打分队列。",
        "kind": "release",
    },
    {
        "title": "新增「母题配置」用户页 /my-topics/config",
        "description": "普通用户可在 /my-topics/config 管理自己的母题：新建、编辑、停用、fork 系统模板。系统模板标记为只读，引导用户 fork 后个性化。原有 /admin/mother-topics 定位调整为「系统母题模板库」。",
        "kind": "release",
    },
    {
        "title": "打分接口 per-user 隔离",
        "description": "score / score-batch / match 接口按「系统模板 + 当前用户的 fork」过滤母题，确保用户修改母题后打分结果立即生效，不再被全局共享的 admin 配置覆盖。",
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
