"""用户自定义降噪规则表 mute_rules

Revision ID: d2b7f9a41c05
Revises: c7a4e9f21b86
Create Date: 2026-10-27

#171 用户自定义降噪：按关键词 / 信源 / 域名静音内容，只影响当前用户
可见的 contents 列表与 today-picks，不物理删除内容数据。

- rule_type 限定 'keyword' | 'source' | 'domain'（CHECK 约束）：
  - keyword → title/summary 大小写不敏感包含；
  - source  → 信源 ID 精确等值（value 存 ID 的字符串形式）；
  - domain  → 内容 url 的 host 等值（写入前归一去 www. 前缀）。
- 每类规则每用户上限 50 条由 service 层校验，表层面只用
  UNIQUE(user_id, rule_type, value) 防重复。
- 纯增量新表（无数据回填、不改既有表），downgrade 直接删表。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2b7f9a41c05"
down_revision: str | None = "c7a4e9f21b86"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "mute_rules"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=False,
            comment="规则归属用户，仅对该用户生效",
        ),
        sa.Column(
            "rule_type",
            sa.String(length=16),
            nullable=False,
            comment="keyword=标题/摘要包含；source=信源 ID 等值；domain=url host 等值",
        ),
        sa.Column("value", sa.Text(), nullable=False, comment="匹配值（domain 写入前已归一去 www. 前缀）"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("rule_type IN ('keyword', 'source', 'domain')", name="ck_mute_rules_rule_type"),
        sa.UniqueConstraint("user_id", "rule_type", "value", name="uq_mute_rules_user_type_value"),
    )
    op.create_index("ix_mute_rules_user_id", _TABLE, ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_mute_rules_user_id", table_name=_TABLE)
    op.drop_table(_TABLE)
