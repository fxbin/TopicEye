"""seed release v0.7.0

Revision ID: 5a6b7c8d9e0f
Revises: f1b4a146437c
Create Date: 2026-07-18 10:00:00

发布 v0.7.0：统计仪表盘可视化升级、统计接口性能优化、前后端代码结构
重构（公共组件/helper 体系、兼容层清理）、阅读器翻译快照修复。
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "5a6b7c8d9e0f"
down_revision = "f1b4a146437c"
branch_labels = None
depends_on = None


_VERSION = "v0.7.0"
_ITEMS = [
    {
        "title": "统计仪表盘可视化升级",
        "description": "分类分布改为分层组合（概览条 + Top10 表 + 蓝海卡），突出低量高分的蓝海分类；长尾分类可折叠，避免被头部分类压扁。",
        "kind": "improvement",
    },
    {
        "title": "统计接口性能优化",
        "description": "隔离缓存失效域、延长 TTL、加骨架屏，解决统计接口在高数据量下响应慢的问题。",
        "kind": "improvement",
    },
    {
        "title": "后端基础设施收敛",
        "description": "抽取 SQLite 事务重试、admin 校验、HTTP 重试、digest 基类等公共 helper；清理 digest/time/get_db/config/_post_sync_pipeline 等兼容 re-export 层；统一时间获取与数据库会话入口，降低重复度。",
        "kind": "improvement",
    },
    {
        "title": "前端公共组件体系",
        "description": "抽取 Surface/PanelTitle/StatTile/Pagination/FieldLabel 等公共组件，统一 CHART_COLORS/Tone/LEVEL_CONFIG 设计 token；today-picks 等页面拆分展示组件、数据获取与静态配置。",
        "kind": "improvement",
    },
    {
        "title": "阅读器翻译快照查询修复",
        "description": "translate_snapshot 改按 content_id 查询而非主键 id，修复翻译缓存命中错误快照的问题。",
        "kind": "fix",
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
