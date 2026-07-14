"""replace planned v0.6.0 with the reader and curation release

Revision ID: 2c3d4e5f6a7b
Revises: 1b2c3d4e5f6a
Create Date: 2026-07-14 18:30:00
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "2c3d4e5f6a7b"
down_revision = "1b2c3d4e5f6a"
branch_labels = None
depends_on = None


_RELEASE_VERSION = "v0.6.0"
_TEMP_VERSION = "v0.6.1"
_RELEASE_ITEMS = [
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
_REPLACED_PLANNED_ITEMS = [
    {
        "title": "多用户配额与状态外移",
        "description": "原 v0.5.0 内容后移至此。LLM 配额按 user_id 分桶、进程内状态外移 Redis、认证限流改按用户。这是规模化的前提条件，不是竞争力本身——只在北极星趋势上升后做。",
        "kind": "roadmap",
    },
    {
        "title": "支付订阅（Stripe only）",
        "description": "严格按最小切片顺序：catalog 数值化(v0.4 已做)→单点配额强制→订阅数据模型(subscriptions/payment_events + User 扩列)→单网关 checkout→webhook 幂等签名验证→Stripe Customer Portal。不碰微信/支付宝/多网关抽象。",
        "kind": "roadmap",
    },
    {
        "title": "触发条件",
        "description": "启动前提：today-picks DAU 北极星指标有上升趋势 + 出现真实云服务需求（有人主动问能否托管）。否则继续打磨 v0.4/v0.5，不过早变现。给规模/便利性收费，不给核心功能收费。",
        "kind": "roadmap",
    },
]


def _items_sql(bind) -> str:
    return ":items" if bind.dialect.name == "sqlite" else "CAST(:items AS JSON)"


def _now_sql(bind) -> str:
    return "CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "NOW()"


def _insert_release(bind, version: str) -> None:
    now_sql = _now_sql(bind)
    bind.execute(
        sa.text(
            f"""
            INSERT INTO product_updates (version, status, shipped_at, items, created_at, updated_at)
            VALUES (:version, 'shipped', {now_sql}, {_items_sql(bind)}, {now_sql}, {now_sql})
            """
        ),
        {"version": version, "items": json.dumps(_RELEASE_ITEMS, ensure_ascii=False)},
    )


def upgrade() -> None:
    bind = op.get_bind()
    current = bind.execute(
        sa.text("SELECT id FROM product_updates WHERE version = :version"),
        {"version": _RELEASE_VERSION},
    ).fetchone()
    if current is None:
        _insert_release(bind, _RELEASE_VERSION)
    else:
        now_sql = _now_sql(bind)
        bind.execute(
            sa.text(
                f"""
                UPDATE product_updates
                SET status = 'shipped', target_date = NULL, shipped_at = {now_sql},
                    items = {_items_sql(bind)}, updated_at = {now_sql}
                WHERE id = :id
                """
            ),
            {"id": current[0], "items": json.dumps(_RELEASE_ITEMS, ensure_ascii=False)},
        )
    bind.execute(sa.text("DELETE FROM product_updates WHERE version = :version"), {"version": _TEMP_VERSION})


def downgrade() -> None:
    bind = op.get_bind()
    now_sql = _now_sql(bind)
    bind.execute(
        sa.text(
            f"""
            UPDATE product_updates
            SET status = 'planned', target_date = '2027-01-31', shipped_at = NULL,
                items = {_items_sql(bind)}, updated_at = {now_sql}
            WHERE version = :version
            """
        ),
        {"version": _RELEASE_VERSION, "items": json.dumps(_REPLACED_PLANNED_ITEMS, ensure_ascii=False)},
    )
    exists = bind.execute(
        sa.text("SELECT id FROM product_updates WHERE version = :version"),
        {"version": _TEMP_VERSION},
    ).fetchone()
    if exists is None:
        _insert_release(bind, _TEMP_VERSION)
