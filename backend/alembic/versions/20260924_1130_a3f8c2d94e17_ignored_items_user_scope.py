"""ignored_items 按用户隔离

Revision ID: a3f8c2d94e17
Revises: f5d8a2b6c9e0
Create Date: 2026-09-24

不感兴趣记录此前没有 user_id，任何登录用户的忽略都会全局影响所有用户
（内容列表全局排除、他人兴趣向量也被拉低）。本迁移：

- 新增可空 user_id 列（FK users.id, ON DELETE CASCADE）：
  - NULL = 管理员全局屏蔽，对所有人生效（存量行保持 NULL，行为不变）；
  - 非 NULL = 用户个人「不感兴趣」，只对该用户生效。
- 唯一约束从 content_id 换成 (user_id, content_id)。
  PostgreSQL 默认 NULLS DISTINCT，全局屏蔽行 (NULL, content_id) 的去重
  仍由 repository 写入前检查保证（与旧行为一致）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3f8c2d94e17"
down_revision: str | None = "f5d8a2b6c9e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "ignored_items"


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=True,
            comment="NULL=管理员全局屏蔽；非 NULL=用户个人不感兴趣",
        ),
    )
    op.drop_constraint("uq_ignored_content", _TABLE, type_="unique")
    op.create_unique_constraint("uq_ignored_user_content", _TABLE, ["user_id", "content_id"])


def downgrade() -> None:
    op.drop_constraint("uq_ignored_user_content", _TABLE, type_="unique")
    op.create_unique_constraint("uq_ignored_content", _TABLE, ["content_id"])
    op.drop_column(_TABLE, "user_id")
