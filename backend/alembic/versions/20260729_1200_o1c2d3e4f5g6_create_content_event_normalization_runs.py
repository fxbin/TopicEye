"""create content event normalization run and lease tables

Revision ID: o1c2d3e4f5g6
Revises: n0b1c2d3e4f5
Create Date: 2026-07-29 12:00:00
"""

import sqlalchemy as sa

from alembic import op

revision = "o1c2d3e4f5g6"
down_revision = "n0b1c2d3e4f5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_event_normalization_leases",
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("fencing_token", sa.Integer(), server_default="0", nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="ck_content_event_normalization_leases_fence",
        ),
        sa.PrimaryKeyConstraint("scope_key"),
    )
    op.create_index(
        "ix_content_event_normalization_leases_expiry",
        "content_event_normalization_leases",
        ["lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "content_event_normalization_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("scope_key", sa.String(length=80), nullable=False),
        sa.Column("owner_user_id", sa.Integer(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("mode", sa.String(length=6), nullable=False),
        sa.Column("status", sa.String(length=9), server_default="running", nullable=False),
        sa.Column("fencing_token", sa.Integer(), nullable=False),
        sa.Column("lease_token", sa.String(length=64), nullable=False),
        sa.Column("window_hours", sa.Integer(), nullable=False),
        sa.Column("classifier_version", sa.String(length=100), nullable=False),
        sa.Column("scanned_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("pending_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("standalone_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_event_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_member_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("llm_call_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("predictions", sa.JSON(), nullable=True),
        sa.Column("model_routes", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "mode IN ('shadow', 'write')",
            name="ck_content_event_normalization_runs_mode",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed')",
            name="ck_content_event_normalization_runs_status",
        ),
        sa.CheckConstraint(
            "fencing_token >= 1",
            name="ck_content_event_normalization_runs_fence",
        ),
        sa.CheckConstraint(
            "window_hours >= 1",
            name="ck_content_event_normalization_runs_window",
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["users.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scope_key",
            "idempotency_key",
            name="uq_content_event_normalization_runs_scope_key",
        ),
    )
    op.create_index(
        "ix_content_event_normalization_runs_scope_started",
        "content_event_normalization_runs",
        ["scope_key", sa.text("started_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_content_event_normalization_runs_status_started",
        "content_event_normalization_runs",
        ["status", sa.text("started_at DESC")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_content_event_normalization_runs_status_started",
        table_name="content_event_normalization_runs",
    )
    op.drop_index(
        "ix_content_event_normalization_runs_scope_started",
        table_name="content_event_normalization_runs",
    )
    op.drop_table("content_event_normalization_runs")
    op.drop_index(
        "ix_content_event_normalization_leases_expiry",
        table_name="content_event_normalization_leases",
    )
    op.drop_table("content_event_normalization_leases")
