"""add translation fields to article_snapshots

Revision ID: f1b4a146437c
Revises: bb473c6a4315
Create Date: 2026-07-18 03:01:30.355508

仅给 article_snapshots 加中文翻译缓存字段（text_content_zh / content_blocks_zh）。
手写迁移，排除 autogenerate 检测到的无关历史漂移。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1b4a146437c'
down_revision: Union[str, None] = 'bb473c6a4315'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('article_snapshots', sa.Column('text_content_zh', sa.Text(), nullable=True))
    op.add_column('article_snapshots', sa.Column('content_blocks_zh', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('article_snapshots', 'content_blocks_zh')
    op.drop_column('article_snapshots', 'text_content_zh')
