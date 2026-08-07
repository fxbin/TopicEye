"""add trend provenance metadata and frozen member truth

Revision ID: t0e1f2a3b4c5
Revises: s4e5f6g7h8i9
Create Date: 2026-08-06 10:30:00
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "t0e1f2a3b4c5"
down_revision = "s4e5f6g7h8i9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("topic_trends") as batch_op:
        batch_op.add_column(
            sa.Column(
                "calculation_version",
                sa.String(length=50),
                nullable=False,
                server_default="legacy-v1",
            )
        )
        batch_op.add_column(sa.Column("window_start", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("window_end", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column(
                "provenance_status",
                sa.String(length=30),
                nullable=False,
                server_default="unavailable",
            )
        )

    # Legacy topic rows may retain a small `top_items` projection.  It is not
    # enough to recreate membership, but it is more informative than a fully
    # unavailable keyword snapshot.  Empty JSON arrays remain unavailable.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        non_empty_top_items = "top_items::text NOT IN ('[]', 'null')"
    else:
        non_empty_top_items = "CAST(top_items AS TEXT) NOT IN ('[]', 'null', '')"
    op.execute(
        sa.text(
            "UPDATE topic_trends "
            "SET provenance_status = 'sample_only' "
            "WHERE topic_id IS NOT NULL "
            "AND top_items IS NOT NULL "
            f"AND {non_empty_top_items}"
        )
    )

    op.create_table(
        "topic_trend_members",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "trend_id",
            sa.Integer(),
            sa.ForeignKey("topic_trends.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_id",
            sa.Integer(),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("selected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("title_snapshot", sa.String(length=500), nullable=False),
        sa.Column("url_snapshot", sa.String(length=1024), nullable=False),
        sa.Column("source_id_snapshot", sa.Integer(), nullable=True),
        sa.Column("source_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("source_type_snapshot", sa.String(length=50), nullable=True),
        sa.Column("platform_snapshot", sa.String(length=100), nullable=True),
        sa.Column("published_at_snapshot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("crawled_at_snapshot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("time_basis", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("trend_id", "content_id", name="uq_topic_trend_member_content"),
    )
    op.create_index(
        "ix_topic_trend_members_trend_position",
        "topic_trend_members",
        ["trend_id", "position"],
    )
    op.create_index("ix_topic_trend_members_content_id", "topic_trend_members", ["content_id"])


def downgrade() -> None:
    op.drop_index("ix_topic_trend_members_content_id", table_name="topic_trend_members")
    op.drop_index("ix_topic_trend_members_trend_position", table_name="topic_trend_members")
    op.drop_table("topic_trend_members")
    with op.batch_alter_table("topic_trends") as batch_op:
        batch_op.drop_column("provenance_status")
        batch_op.drop_column("window_end")
        batch_op.drop_column("window_start")
        batch_op.drop_column("calculation_version")
