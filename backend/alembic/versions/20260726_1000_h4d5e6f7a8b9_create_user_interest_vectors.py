"""create user_interest_vectors table

Revision ID: h4d5e6f7a8b9
Revises: g3c4d5e6f7a8
Create Date: 2026-07-26 10:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "h4d5e6f7a8b9"
down_revision = "g3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_interest_vectors",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tag", sa.String(100), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("signal_source", sa.String(30), nullable=False, server_default="manual"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", "tag", name="uq_user_interest_tag"),
    )
    op.create_index("ix_user_interest_vectors_user", "user_interest_vectors", ["user_id"])
    op.create_index(
        "ix_user_interest_vectors_user_weight",
        "user_interest_vectors",
        ["user_id", "weight"],
    )


def downgrade() -> None:
    op.drop_table("user_interest_vectors")
