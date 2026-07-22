"""create read_records table for report read tracking

Revision ID: r3a4d5r6e7c8
Revises: 7e8f9a0b1c2d
Create Date: 2026-07-22 10:30:00
"""
from alembic import op
import sqlalchemy as sa

revision = 'r3a4d5r6e7c8'
down_revision = '7e8f9a0b1c2d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'read_records',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_type', sa.String(length=32), nullable=False),
        sa.Column('target_key', sa.String(length=64), nullable=False),
        sa.Column('target_id', sa.Integer(), nullable=True),
        sa.Column('read_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('accumulated_ms', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_progress', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('depth', sa.String(length=16), nullable=False, server_default='read'),
        sa.Column('topic_keywords', sa.JSON(), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=True),
        sa.Column('first_read_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('last_read_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'target_type', 'target_key', name='uq_read_record_user_target'),
    )
    op.create_index('ix_read_records_user_id', 'read_records', ['user_id'])
    op.create_index('ix_read_record_user_type_last_read', 'read_records', ['user_id', 'target_type', 'last_read_at'])
    op.create_index('ix_read_record_user_last_read', 'read_records', ['user_id', 'last_read_at'])


def downgrade() -> None:
    op.drop_index('ix_read_record_user_last_read', table_name='read_records')
    op.drop_index('ix_read_record_user_type_last_read', table_name='read_records')
    op.drop_index('ix_read_records_user_id', table_name='read_records')
    op.drop_table('read_records')
