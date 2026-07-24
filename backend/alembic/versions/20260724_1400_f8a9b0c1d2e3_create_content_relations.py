"""create content_relations table

Revision ID: a1b2c3d4e5f6
Revises: r3a4d5r6e7c8
Create Date: 2026-07-24 14:00:00

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "f8a9b0c1d2e3"
down_revision = "r3a4d5r6e7c8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_relations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_id", sa.Integer(), sa.ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("relation_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.5"),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("source_id", "target_id", "relation_type", name="uq_content_relations_triple"),
    )
    op.create_index("ix_content_relations_source", "content_relations", ["source_id"])
    op.create_index("ix_content_relations_target", "content_relations", ["target_id"])
    op.create_index("ix_content_relations_type", "content_relations", ["relation_type"])


def downgrade() -> None:
    op.drop_index("ix_content_relations_type", table_name="content_relations")
    op.drop_index("ix_content_relations_target", table_name="content_relations")
    op.drop_index("ix_content_relations_source", table_name="content_relations")
    op.drop_table("content_relations")
