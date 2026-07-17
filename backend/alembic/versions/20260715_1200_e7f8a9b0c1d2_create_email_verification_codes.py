"""create email_verification_codes table

Revision ID: e7f8a9b0c1d2
Revises: 3d4e5f6a7b8c
Create Date: 2026-07-15 12:00:00

新增邮箱验证码表，支撑注册流程的邮箱验证。
验证码以 sha256 哈希存储，支持过期清理与防重放。
"""
# author: fxbin

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "e7f8a9b0c1d2"
down_revision = "3d4e5f6a7b8c"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_verification_codes",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("code_hash", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index(
        "ix_email_verification_codes_email",
        "email_verification_codes",
        ["email"],
    )
    op.create_index(
        "ix_email_verification_email_created",
        "email_verification_codes",
        ["email", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_email_verification_email_created",
        table_name="email_verification_codes",
    )
    op.drop_index(
        "ix_email_verification_codes_email",
        table_name="email_verification_codes",
    )
    op.drop_table("email_verification_codes")
