"""create metrics_snapshots table

Revision ID: 9d0e1f2a3b4c
Revises: 8c9d0e1f2a3b
Create Date: 2026-07-20 10:00:00.000000

监控指标快照持久化表。Scheduler 每 60 秒写入一行，
清理任务保留 7 天历史。供 /api/v1/metrics/history 查询历史趋势。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "9d0e1f2a3b4c"
down_revision = "8c9d0e1f2a3b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "metrics_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("uptime_seconds", sa.Float(), nullable=False, server_default="0"),
        # HTTP
        sa.Column("http_total_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_total_errors_5xx", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_error_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("http_p50", sa.Float(), nullable=False, server_default="0"),
        sa.Column("http_p95", sa.Float(), nullable=False, server_default="0"),
        sa.Column("http_p99", sa.Float(), nullable=False, server_default="0"),
        sa.Column("http_in_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("http_rate_limit_hits", sa.Integer(), nullable=False, server_default="0"),
        # LLM
        sa.Column("llm_total_calls", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_total_done", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_total_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_success_rate", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_total_cost_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_total_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_total_output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_p50", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_p95", sa.Float(), nullable=False, server_default="0"),
        sa.Column("llm_p99", sa.Float(), nullable=False, server_default="0"),
        # DB pool
        sa.Column("db_pool_checked_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("db_pool_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("db_pool_utilization", sa.Float(), nullable=False, server_default="0"),
        # Process
        sa.Column("process_rss_mb", sa.Float(), nullable=False, server_default="0"),
        sa.Column("process_cpu_user_s", sa.Float(), nullable=False, server_default="0"),
        sa.Column("process_cpu_sys_s", sa.Float(), nullable=False, server_default="0"),
        # Slow queries
        sa.Column("slow_queries_total", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_metrics_snapshots_captured_at", "metrics_snapshots", ["captured_at"])


def downgrade() -> None:
    op.drop_index("ix_metrics_snapshots_captured_at", table_name="metrics_snapshots")
    op.drop_table("metrics_snapshots")
