"""create evidence_interactions table

Revision ID: g3c4d5e6f7a8
Revises: f2b3c4d5e6f7
Create Date: 2026-07-24 18:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "g3c4d5e6f7a8"
down_revision = "f2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_interactions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("content_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("interaction_type", sa.String(30), nullable=False),
        sa.Column("cross_source_level", sa.String(30), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_evidence_interactions_content", "evidence_interactions", ["content_id"])
    op.create_index("ix_evidence_interactions_type", "evidence_interactions", ["interaction_type"])


def downgrade() -> None:
    op.drop_table("evidence_interactions")
