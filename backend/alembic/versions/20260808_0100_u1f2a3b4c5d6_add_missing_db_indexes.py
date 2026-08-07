"""add missing database indexes for hot query paths

Revision ID: u1f2a3b4c5d6
Revises: t0e1f2a3b4c5
Create Date: 2026-08-08 01:00:00

Indexes added:
  - topic_groups.best_score DESC  — list_ordered_by_best_score()
  - topic_groups.name             — get_or_create(name)
  - content_metrics.content_id     — selectinload(ContentItem.metrics)
  - content_items.topic_id         — list_all_by_topic_id()
  - content_items.source_id        — source_health_repo GROUP BY source_id

These are purely additive CREATE INDEX operations; no data migration,
no column changes, no schema shape change. Safe to downgrade without
data loss.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "u1f2a3b4c5d6"
down_revision = "t0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # topic_groups: list_ordered_by_best_score() — ORDER BY best_score DESC
    op.create_index(
        "ix_topic_groups_best_score",
        "topic_groups",
        [sa.text("best_score DESC")],
    )
    # topic_groups: get_or_create(name) — WHERE name = ?
    op.create_index(
        "ix_topic_groups_name",
        "topic_groups",
        ["name"],
    )
    # content_metrics: selectinload(ContentItem.metrics) — WHERE content_id IN (...)
    op.create_index(
        "ix_content_metrics_content_id",
        "content_metrics",
        ["content_id"],
    )
    # content_items: list_all_by_topic_id() — WHERE topic_id = ? ORDER BY crawled_at DESC
    op.create_index(
        "ix_content_items_topic_id",
        "content_items",
        ["topic_id"],
    )
    # content_items: source_health_repo — WHERE source_id = ? / GROUP BY source_id
    op.create_index(
        "ix_content_items_source_id",
        "content_items",
        ["source_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_source_id", table_name="content_items")
    op.drop_index("ix_content_items_topic_id", table_name="content_items")
    op.drop_index("ix_content_metrics_content_id", table_name="content_metrics")
    op.drop_index("ix_topic_groups_name", table_name="topic_groups")
    op.drop_index("ix_topic_groups_best_score", table_name="topic_groups")
