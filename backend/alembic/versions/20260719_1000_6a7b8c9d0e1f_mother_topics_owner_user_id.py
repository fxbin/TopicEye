"""mother_topics add owner_user_id (per-user + system template)

Revision ID: 6a7b8c9d0e1f
Revises: 5a6b7c8d9e0f
Create Date: 2026-07-19 10:00:00.000000

母题 per-user 化（路线 C：系统模板库 + 用户 fork）。

改造：
- mother_topics 加 owner_user_id（nullable，NULL=系统模板；非 NULL=用户自定义 fork）
- 删除旧的单列 unique index ix_mother_topics_name（name 全局唯一）
- 新增多列 unique constraint (owner_user_id, name) —— 同一 scope 内 name 唯一，
  SQLite 多列 UNIQUE 中 NULL 视为 distinct，系统模板的 name 唯一性由应用层保证
  （与 daily_reports owner_user_id IS NULL 等价处理策略一致）
- 新增索引 (owner_user_id, is_active) 加速 per-user 活跃母题查询
- 外键 fk_mother_topics_owner_user_id -> users.id ON DELETE CASCADE

数据迁移：
- 历史母题 owner_user_id 保持 NULL，自动归为系统模板，无需回填
- 既有 admin 配置的母题变成「系统模板库」，用户首次访问 /my-topics 时
  由应用层 fork_default_templates_for_user 懒触发复制一份到用户名下
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6a7b8c9d0e1f'
down_revision: Union[str, None] = '5a6b7c8d9e0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite batch mode：重建表以支持 drop_index + add_column + 新约束
    with op.batch_alter_table('mother_topics', schema=None) as batch_op:
        # 1. 加 owner_user_id（NULL=系统模板；非 NULL=用户自定义）
        batch_op.add_column(sa.Column(
            'owner_user_id', sa.Integer(), nullable=True,
            comment='NULL=系统模板；非 NULL=用户自定义 fork',
        ))
        # 2. 删除旧的单列 unique index（name 全局唯一不再适用）
        batch_op.drop_index('ix_mother_topics_name')
        # 3. 新增多列 unique constraint：同一 scope 内 name 唯一
        #    SQLite NULL DISTINCT 行为：系统模板行之间不冲突，由应用层保证唯一
        batch_op.create_unique_constraint(
            'uq_mother_topics_owner_name',
            ['owner_user_id', 'name'],
        )
        # 4. 新增索引：per-user 活跃母题查询加速
        batch_op.create_index(
            'ix_mother_topics_owner_active',
            ['owner_user_id', 'is_active'],
            unique=False,
        )
        # 5. 外键：删除用户时级联删除其私有母题
        batch_op.create_foreign_key(
            'fk_mother_topics_owner_user_id', 'users',
            ['owner_user_id'], ['id'],
            ondelete='CASCADE',
        )


def downgrade() -> None:
    with op.batch_alter_table('mother_topics', schema=None) as batch_op:
        batch_op.drop_constraint('fk_mother_topics_owner_user_id', type_='foreignkey')
        batch_op.drop_index('ix_mother_topics_owner_active')
        batch_op.drop_constraint('uq_mother_topics_owner_name', type_='unique')
        batch_op.drop_column('owner_user_id')
        # 恢复旧的单列 unique index
        batch_op.create_index(
            'ix_mother_topics_name',
            ['name'],
            unique=True,
        )
