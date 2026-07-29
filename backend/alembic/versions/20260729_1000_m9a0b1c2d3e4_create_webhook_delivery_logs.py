"""create webhook delivery log table

Revision ID: m9a0b1c2d3e4
Revises: l8a9b0c1d2e3
Create Date: 2026-07-29 10:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "m9a0b1c2d3e4"
down_revision = "l8a9b0c1d2e3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_delivery_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("alert_key", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(50), nullable=False, server_default="source_failure"),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False, server_default="warning"),
        sa.Column("webhook_url_preview", sa.String(120), nullable=False),
        sa.Column("status_code", sa.Integer, nullable=True),
        sa.Column("success", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("response_preview", sa.Text, nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            # ANSI/SQLite CURRENT_TIMESTAMP is also accepted by PostgreSQL.
            # Using now() directly is invalid inside a SQLite DEFAULT clause.
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_index("ix_webhook_logs_created", "webhook_delivery_logs", ["created_at"])
    op.create_index(
        "ix_webhook_logs_event_type",
        "webhook_delivery_logs",
        ["event_type", "created_at"],
    )
    op.create_index("ix_webhook_logs_alert_key", "webhook_delivery_logs", ["alert_key"])


def downgrade() -> None:
    op.drop_index("ix_webhook_logs_alert_key", table_name="webhook_delivery_logs")
    op.drop_index("ix_webhook_logs_event_type", table_name="webhook_delivery_logs")
    op.drop_index("ix_webhook_logs_created", table_name="webhook_delivery_logs")
    op.drop_table("webhook_delivery_logs")
