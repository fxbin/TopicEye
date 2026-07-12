"""create pick_marks table for daily report pick tracking

Revision ID: d5e6f7a8b9c0
Revises: c3d4e5f6a7b8
Create Date: 2026-07-12 14:00:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'd5e6f7a8b9c0'
down_revision = 'c3d4e5f6a7b8'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'pick_marks',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('report_date', sa.Date(), nullable=False),
        sa.Column('pick_title', sa.Text(), nullable=False),
        sa.Column('action', sa.Text(), nullable=False),
        sa.Column('pick_category', sa.Text(), nullable=True),
        sa.Column('pick_source_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'report_date', 'pick_title', name='uq_pick_mark_user_date_title'),
    )
    op.create_index('ix_pick_mark_user_date', 'pick_marks', ['user_id', 'report_date'])
    op.create_index('ix_pick_mark_action', 'pick_marks', ['user_id', 'action'])


def downgrade() -> None:
    op.drop_index('ix_pick_mark_action', table_name='pick_marks')
    op.drop_index('ix_pick_mark_user_date', table_name='pick_marks')
    op.drop_table('pick_marks')
