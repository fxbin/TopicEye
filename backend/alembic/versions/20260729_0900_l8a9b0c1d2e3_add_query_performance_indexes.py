"""add query performance indexes

Revision ID: l8a9b0c1d2e3
Revises: k7f8a9b0c1d2
Create Date: 2026-07-29 09:00:00

Adds critical indexes that were identified as missing during slow-query
diagnosis.  The two most impactful additions:

1. ``ai_analyses(content_id, created_at DESC, id DESC)`` — the
   ``latest_analysis_id_subquery`` correlated subquery scans
   ``ai_analyses`` for every content row; without this index each lookup
   is a full table scan on a 36 K-row table.

2. ``content_items(crawled_at DESC)`` — virtually every list endpoint
   filters by ``crawled_at >= cutoff``; the absence of this index forces
   a full scan followed by an in-memory sort.

A composite ``content_items(status, crawled_at DESC)`` is also added for
the common "analyzed items in time window" pattern used by today-picks,
scoring-flow, and count endpoints.
"""

from alembic import op
import sqlalchemy as sa


revision = "l8a9b0c1d2e3"
down_revision = "k7f8a9b0c1d2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Critical: eliminates full-table-scan per content item in lateral joins
    op.create_index(
        "ix_ai_analyses_content_created",
        "ai_analyses",
        ["content_id", sa.text("created_at DESC"), sa.text("id DESC")],
    )

    # 2. Critical: time-range filter on the main content listing queries
    op.create_index(
        "ix_content_items_crawled_at",
        "content_items",
        [sa.text("crawled_at DESC")],
    )

    # 3. Composite: "analyzed items in time window" pattern
    op.create_index(
        "ix_content_items_status_crawled",
        "content_items",
        ["status", sa.text("crawled_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_status_crawled", table_name="content_items")
    op.drop_index("ix_content_items_crawled_at", table_name="content_items")
    op.drop_index("ix_ai_analyses_content_created", table_name="ai_analyses")
