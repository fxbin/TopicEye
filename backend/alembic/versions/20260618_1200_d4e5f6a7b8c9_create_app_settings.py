"""create app_settings table

Revision ID: d4e5f6a7b8c9
Revises: f1a2b3c4d5e6
Create Date: 2026-06-18 12:00:00

补建 app_settings 表（模型已存在但 13 个迁移里漏建）。

后果：所有 RSSHub 类型 source 同步 + admin /settings/rsshub/instances 接口
都会因为 SELECT FROM app_settings 抛 UndefinedTableError 而炸。

Table 字段对齐 app/models/app_setting.py:25 AppSetting：
- key: 主键 VARCHAR(64)
- value: TEXT（JSON 序列化）
- description: VARCHAR(255)
- updated_at: TIMESTAMP WITH TIME ZONE（PG）/ TIMESTAMP（SQLite，
  与 baseline 保持一致；tz-aware 迁移在 SQLite 端是 no-op）

下游约定：20260616_0000_b3f7d2a9c1e4_datetime_columns_tz_aware.py 的
DATETIME_COLUMNS 已硬编码 ('app_settings', 'updated_at')，本迁移建表后
该 tz 迁移在新库首次跑会天然命中，老库走"防御性跳过"安全。
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'd4e5f6a7b8c9'
down_revision = 'f1a2b3c4d5e6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=64), primary_key=True),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('description', sa.String(length=255), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table('app_settings')
