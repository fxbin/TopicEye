"""Metrics snapshot persistence model.

Stores periodic snapshots of the in-memory RequestMetricsCollector to SQLite,
enabling historical trend analysis beyond the 30-minute in-memory ring buffer.
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC

from sqlalchemy import DateTime, Float, Index, Integer
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MetricsSnapshotRecord(Base):
    """A single point-in-time snapshot of all collected metrics.

    Written by the scheduler every 60 seconds, cleaned up after 7 days.
    Queryable via /api/v1/metrics/history for historical trend charts.
    """

    __tablename__ = "metrics_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    uptime_seconds: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── HTTP layer ──
    http_total_requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_total_errors_5xx: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_error_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    http_p50: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    http_p95: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    http_p99: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    http_in_progress: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    http_rate_limit_hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # ── LLM layer ──
    llm_total_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_total_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_total_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_success_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_total_cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_total_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_total_output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_p50: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_p95: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    llm_p99: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── DB pool layer ──
    db_pool_checked_out: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_pool_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    db_pool_utilization: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── Process layer ──
    process_rss_mb: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    process_cpu_user_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    process_cpu_sys_s: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # ── Slow queries ──
    slow_queries_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        Index("ix_metrics_snapshots_captured_at", "captured_at"),
    )

    def __repr__(self) -> str:
        return f"<MetricsSnapshotRecord {self.captured_at} req={self.http_total_requests}>"
