"""create source_evidence_profiles table

Revision ID: f2b3c4d5e6f7
Revises: a1b2c3d4e5f7
Create Date: 2026-07-24 17:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "f2b3c4d5e6f7"
down_revision = "a1b2c3d4e5f7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_evidence_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("publisher_identity", sa.String(100), nullable=False),
        sa.Column("publisher_family", sa.String(100), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("publisher_kind", sa.String(30), nullable=False, server_default="unknown"),
        sa.Column("official_domains", sa.JSON(), nullable=True),
        sa.Column("verification_proof_url", sa.String(1024), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("managed_by_admin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", name="uq_evidence_profile_source"),
    )
    op.create_index("ix_evidence_profile_identity", "source_evidence_profiles", ["publisher_identity"])


def downgrade() -> None:
    op.drop_table("source_evidence_profiles")
