"""add durable analysis claim lease

Revision ID: k7f8a9b0c1d2
Revises: j6e7f8a9b0c1
Create Date: 2026-07-28 19:00:00
"""

from alembic import op
import sqlalchemy as sa


revision = "k7f8a9b0c1d2"
down_revision = "j6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable fields keep all pre-existing ANALYZING rows recoverable through
    # the legacy updated_at stale path until their next durable claim.
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.add_column(sa.Column("analysis_claim_token", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("analysis_lease_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_content_analysis_lease",
        "content_items",
        ["status", "analysis_lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_analysis_lease", table_name="content_items")
    with op.batch_alter_table("content_items") as batch_op:
        batch_op.drop_column("analysis_lease_expires_at")
        batch_op.drop_column("analysis_claim_token")
