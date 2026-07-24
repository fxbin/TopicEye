"""create content_evidence tables

Revision ID: e1a2b3c4d5f6
Revises: f8a9b0c1d2e3
Create Date: 2026-07-24 15:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "e1a2b3c4d5f6"
down_revision = "f8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_evidence_marks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("cross_source_level", sa.String(30), nullable=False, server_default="none"),
        sa.Column("platform_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("platforms", sa.JSON(), nullable=True),
        sa.Column("has_primary_source", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_official_source", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("independent_publisher_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("content_id", "owner_user_id", name="uq_evidence_marks_scope"),
    )
    op.create_index("ix_evidence_marks_content", "content_evidence_marks", ["content_id"])
    op.create_index("ix_evidence_marks_owner", "content_evidence_marks", ["owner_user_id"])

    op.create_table(
        "content_evidence_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("mark_id", sa.Integer(), sa.ForeignKey("content_evidence_marks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("evidence_content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="SET NULL"), nullable=True),
        sa.Column("evidence_url", sa.String(1024), nullable=True),
        sa.Column("evidence_type", sa.String(30), nullable=False),
        sa.Column("publisher_family", sa.String(100), nullable=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="SET NULL"), nullable=True),
        sa.Column("similarity_score", sa.Float(), nullable=True),
        sa.Column("time_delta_minutes", sa.Float(), nullable=True),
        sa.Column("match_basis", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_links_mark", "content_evidence_links", ["mark_id"])


def downgrade() -> None:
    op.drop_table("content_evidence_links")
    op.drop_table("content_evidence_marks")
