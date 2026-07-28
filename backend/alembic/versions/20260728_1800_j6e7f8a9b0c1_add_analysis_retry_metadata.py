"""add persistent analysis retry metadata

Revision ID: j6e7f8a9b0c1
Revises: i5e6f7a8b9c0
Create Date: 2026-07-28 18:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "j6e7f8a9b0c1"
down_revision = "i5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.add_column(sa.Column("analysis_attempts", sa.Integer(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("analysis_next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_content_analysis_retry", "content_items", ["status", "analysis_next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_content_analysis_retry", table_name="content_items")
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.drop_column("analysis_next_retry_at")
        batch_op.drop_column("analysis_attempts")
