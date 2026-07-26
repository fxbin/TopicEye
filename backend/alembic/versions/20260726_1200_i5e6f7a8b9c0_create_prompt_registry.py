"""create prompt_registry table

Revision ID: i5e6f7a8b9c0
Revises: h4d5e6f7a8b9
Create Date: 2026-07-26 12:00:00
"""

from alembic import op
import sqlalchemy as sa

revision = "i5e6f7a8b9c0"
down_revision = "h4d5e6f7a8b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "prompt_registry",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(80), nullable=False, unique=True),
        sa.Column("scene", sa.String(50), nullable=False),
        sa.Column("description", sa.String(200), nullable=False, server_default=""),
        sa.Column("source_file", sa.String(200), nullable=False, server_default=""),
        sa.Column("content_preview", sa.Text(), nullable=False, server_default=""),
        sa.Column("full_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("version_hash", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.current_timestamp(),
        ),
    )
    op.create_index("ix_prompt_registry_scene", "prompt_registry", ["scene"])


def downgrade() -> None:
    op.drop_index("ix_prompt_registry_scene", table_name="prompt_registry")
    op.drop_table("prompt_registry")
