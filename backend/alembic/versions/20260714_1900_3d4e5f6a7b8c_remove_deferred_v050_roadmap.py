"""remove the deferred roadmap item from v0.5.0 release notes

Revision ID: 3d4e5f6a7b8c
Revises: 2c3d4e5f6a7b
Create Date: 2026-07-14 19:00:00

The product-updates menu is a release history.  v0.5.0 has already shipped,
so its deferred v0.5.1 work must not be presented as part of that release.
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "3d4e5f6a7b8c"
down_revision = "2c3d4e5f6a7b"
branch_labels = None
depends_on = None


_VERSION = "v0.5.0"
_DEFERRED_ITEM = {
    "title": "评分快照基座（推到 v0.5.1）",
    "description": "scoring_snapshots + scoring_config_versions 表 + 写入点整体推迟到 v0.5.1。理由: 对比页需要历史数据积累, 而 CONFIG 自项目起未变过, 现在做对比没对象。先让 Agent API 站住, 数据基座等真有调参需求时再做。",
    "kind": "roadmap",
}


def _load_items(bind) -> tuple[int | None, list[dict]]:
    row = bind.execute(
        sa.text("SELECT id, items FROM product_updates WHERE version = :version"),
        {"version": _VERSION},
    ).fetchone()
    if row is None:
        return None, []
    items = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    return row[0], list(items)


def _store_items(bind, row_id: int, items: list[dict]) -> None:
    now_sql = "CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "NOW()"
    items_sql = ":items" if bind.dialect.name == "sqlite" else "CAST(:items AS JSON)"
    bind.execute(
        sa.text(
            f"UPDATE product_updates SET items = {items_sql}, updated_at = {now_sql} WHERE id = :id"
        ),
        {"id": row_id, "items": json.dumps(items, ensure_ascii=False)},
    )


def upgrade() -> None:
    bind = op.get_bind()
    row_id, items = _load_items(bind)
    if row_id is None:
        return
    filtered = [item for item in items if item.get("title") != _DEFERRED_ITEM["title"]]
    if len(filtered) != len(items):
        _store_items(bind, row_id, filtered)


def downgrade() -> None:
    bind = op.get_bind()
    row_id, items = _load_items(bind)
    if row_id is None or any(item.get("title") == _DEFERRED_ITEM["title"] for item in items):
        return
    _store_items(bind, row_id, [*items, _DEFERRED_ITEM])
