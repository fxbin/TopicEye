"""preserve reader structure and extraction outcomes

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-07-14 17:30:00
"""

from alembic import op
import sqlalchemy as sa


revision = "f7a8b9c0d1e2"
down_revision = "e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("article_snapshots") as batch_op:
        batch_op.add_column(sa.Column("content_blocks", sa.JSON(), nullable=True))

    op.create_table(
        "article_reader_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("extraction_method", sa.String(length=24), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_article_reader_events_content_created",
        "article_reader_events",
        ["content_id", "created_at"],
    )
    op.create_index(
        "ix_article_reader_events_outcome_created",
        "article_reader_events",
        ["outcome", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_article_reader_events_outcome_created", table_name="article_reader_events")
    op.drop_index("ix_article_reader_events_content_created", table_name="article_reader_events")
    op.drop_table("article_reader_events")
    with op.batch_alter_table("article_snapshots") as batch_op:
        batch_op.drop_column("content_blocks")
