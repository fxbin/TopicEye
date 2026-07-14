"""create reader-mode article snapshots

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-07-14 16:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "e6f7a8b9c0d1"
down_revision = "d5e6f7a8b9c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "article_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("canonical_url", sa.String(length=1024), nullable=False),
        sa.Column("fetch_status", sa.String(length=24), nullable=False, server_default="ready"),
        sa.Column("extraction_method", sa.String(length=24), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("byline", sa.String(length=255), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("text_content", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("reading_minutes", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("content_id", name="uq_article_snapshots_content_id"),
    )
    op.create_index("ix_article_snapshots_expires_at", "article_snapshots", ["expires_at"])
    op.create_index("ix_article_snapshots_fetch_status", "article_snapshots", ["fetch_status"])


def downgrade() -> None:
    op.drop_index("ix_article_snapshots_fetch_status", table_name="article_snapshots")
    op.drop_index("ix_article_snapshots_expires_at", table_name="article_snapshots")
    op.drop_table("article_snapshots")
