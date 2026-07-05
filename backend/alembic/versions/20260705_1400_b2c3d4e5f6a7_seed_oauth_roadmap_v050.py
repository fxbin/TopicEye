"""seed oauth roadmap item into v0.5.0

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05 14:00:00

往 product_updates.v0.5.0 的 items JSON 数组追加一条 OAuth 路线图项。
遵循项目约定：product_updates 数据走 Alembic seed，不走 startup（见
product_feedback.py:202 注释「避免数据/代码双源」）。

幂等：upgrade 先检查 items 是否已含同名 title，避免重复追加；
downgrade 按 title 精确移除该条目，不动其它项。

注意：本迁移操作 PG 的 json/jsonb 列。项目 OLTP 库为 PG（生产）或
SQLite（本地开发）。SQLite 无原生 jsonb 操作符，故采用 SQLAlchemy
exec_driver_sql 走各库方言兼容的最小操作：先 SELECT items 到 Python，
在 Python 层 append/remove，再 UPDATE 写回。此方式对 PG/SQLite 都安全。
"""
from alembic import op
import sqlalchemy as sa
import json


# revision identifiers, used by Alembic.
revision = 'b2c3d4e5f6a7'
down_revision = 'a1b2c3d4e5f6'
branch_labels = None
depends_on = None


_OAUTH_ENTRY = {
    "title": "OAuth 登录与开源准备",
    "description": "接入 Google / GitHub OAuth 登录（Authlib），新增 user_oauth_accounts 关联表与自动合并策略（已验证邮箱自动关联，未验证邮箱拒绝以防劫持）；password_hash 改 nullable 支持纯 OAuth 用户；前端登录页加第三方登录按钮与回调消费页（token 走 URL fragment）。为项目开源化铺路。",
    "kind": "roadmap",
}
_OAUTH_TITLE = _OAUTH_ENTRY["title"]
_VERSION = "v0.5.0"


def _load_items(bind, version: str) -> tuple[int | None, list[dict]]:
    """返回 (row_id, items_list)。row_id=None 表示该版本不存在。"""
    row = bind.execute(
        sa.text("SELECT id, items FROM product_updates WHERE version = :v"),
        {"v": version},
    ).fetchone()
    if row is None:
        return None, []
    # PG: items 已是 list；SQLite: 可能是 str 或 list
    items = row[1]
    if isinstance(items, str):
        items = json.loads(items)
    return row[0], list(items)


def _has_title(items: list[dict], title: str) -> bool:
    return any(it.get("title") == title for it in items)


def upgrade() -> None:
    bind = op.get_bind()
    row_id, items = _load_items(bind, _VERSION)
    if row_id is None:
        # 版本记录不存在（全新库未跑过 baseline seed）——跳过，由后续 seed 补
        return
    if _has_title(items, _OAUTH_TITLE):
        # 已存在，幂等返回
        return
    items.append(_OAUTH_ENTRY)
    bind.execute(
        sa.text("UPDATE product_updates SET items = CAST(:items AS JSON), updated_at = NOW() WHERE id = :id"),
        {"items": json.dumps(items, ensure_ascii=False), "id": row_id},
    )


def downgrade() -> None:
    bind = op.get_bind()
    row_id, items = _load_items(bind, _VERSION)
    if row_id is None:
        return
    if not _has_title(items, _OAUTH_TITLE):
        return
    filtered = [it for it in items if it.get("title") != _OAUTH_TITLE]
    bind.execute(
        sa.text("UPDATE product_updates SET items = CAST(:items AS JSON), updated_at = NOW() WHERE id = :id"),
        {"items": json.dumps(filtered, ensure_ascii=False), "id": row_id},
    )
