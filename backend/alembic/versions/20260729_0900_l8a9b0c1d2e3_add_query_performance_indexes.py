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

import sqlalchemy as sa

from alembic import op

revision = "l8a9b0c1d2e3"
down_revision = "k7f8a9b0c1d2"
branch_labels = None
depends_on = None


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {
        index["name"]
        for index in inspector.get_indexes(table_name)
        if index.get("name")
    }


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    analysis_indexes = _index_names(inspector, "ai_analyses")
    content_indexes = _index_names(inspector, "content_items")

    # 1. Critical: eliminates full-table-scan per content item in lateral joins
    if "ix_ai_analyses_content_created" not in analysis_indexes:
        op.create_index(
            "ix_ai_analyses_content_created",
            "ai_analyses",
            ["content_id", sa.text("created_at DESC"), sa.text("id DESC")],
        )

    # 2. Critical: time-range filter on the main content listing queries
    if "ix_content_items_crawled_at" not in content_indexes:
        op.create_index(
            "ix_content_items_crawled_at",
            "content_items",
            [sa.text("crawled_at DESC")],
        )

    # This index was already introduced by c3d4e5f6a7b8. Keep the guard because
    # SQLite DDL is non-transactional and an interrupted prior attempt may have
    # created only part of this revision.
    if "ix_content_items_status_crawled" not in content_indexes:
        op.create_index(
            "ix_content_items_status_crawled",
            "content_items",
            ["status", sa.text("crawled_at DESC")],
        )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    analysis_indexes = _index_names(inspector, "ai_analyses")
    content_indexes = _index_names(inspector, "content_items")

    # c3d4e5f6a7b8 owns ix_content_items_status_crawled, so downgrading this
    # revision must preserve it. The other two names first appear here.
    if "ix_content_items_crawled_at" in content_indexes:
        op.drop_index("ix_content_items_crawled_at", table_name="content_items")
    if "ix_ai_analyses_content_created" in analysis_indexes:
        op.drop_index("ix_ai_analyses_content_created", table_name="ai_analyses")
