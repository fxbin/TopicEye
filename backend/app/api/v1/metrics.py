"""
Prometheus 兼容的 /metrics 端点。

暴露 TopicEye 的关键运行指标，可被 Prometheus / Grafana / VictoriaMetrics
抓取。无需第三方库——直接输出 Prometheus text format。

指标覆盖：
- topiceye_sources_total{status}: 按 status 分的 source 数
- topiceye_content_total{status}: 按 status 分的内容数
- topiceye_content_recent_24h: 最近 24h 新增内容数
- topiceye_analyses_total: 分析总数
- topiceye_job_runs_total{status}: job 运行数（从 job_execution_logs）
- topiceye_uptime_seconds: 进程运行时间
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Response
from sqlalchemy import func, select

from app.core.database import async_session
from app.models.content import ContentItem
from app.models.notification import Notification
from app.models.scheduled_job import JobExecutionLog
from app.models.source import Source

router = APIRouter(prefix="/metrics", tags=["metrics"])

_START_TIME = time.monotonic()


@router.get("")
async def prometheus_metrics():
    """Prometheus text format metrics."""
    lines: list[str] = []
    now = datetime.now(UTC)

    def gauge(name: str, value, help_text: str = "", labels: dict | None = None):
        if help_text:
            lines.append(f"# HELP {name} {help_text}")
        lines.append(f"# TYPE {name} gauge")
        if labels:
            label_str = ",".join(f'{k}="{v}"' for k, v in labels.items())
            lines.append(f"{name}{{{label_str}}} {value}")
        else:
            lines.append(f"{name} {value}")

    async with async_session() as db:
        # ── Sources by status ──
        rows = await db.execute(select(Source.status, func.count()).group_by(Source.status))
        for status, count in rows:
            gauge("topiceye_sources_total", count, "Sources by status", {"status": status})

        # ── Content by status ──
        rows = await db.execute(select(ContentItem.status, func.count()).group_by(ContentItem.status))
        for status, count in rows:
            gauge("topiceye_content_total", count, "Content items by status", {"status": status})

        # ── Recent content (24h) ──
        cutoff = now - timedelta(hours=24)
        recent = (
            await db.scalar(select(func.count()).select_from(ContentItem).where(ContentItem.crawled_at >= cutoff)) or 0
        )
        gauge("topiceye_content_recent_24h", recent, "Content items crawled in last 24h")

        # ── Analyses total ──
        analyses = await db.scalar(select(func.count()).select_from(JobExecutionLog.__table__)) or 0
        # Actually count from a known analysis table; JobExecutionLog is jobs, not analyses
        from app.models.analysis import AiAnalysis

        analyses = await db.scalar(select(func.count()).select_from(AiAnalysis)) or 0
        gauge("topiceye_analyses_total", analyses, "Total AI analyses")

        # ── Job runs by status (last 24h) ──
        rows = await db.execute(
            select(JobExecutionLog.status, func.count())
            .where(JobExecutionLog.started_at >= cutoff)
            .group_by(JobExecutionLog.status)
        )
        for status, count in rows:
            gauge("topiceye_job_runs_total", count, "Job runs in last 24h by status", {"status": status})

        # ── Notifications unread ──
        unread = await db.scalar(select(func.count()).select_from(Notification)) or 0
        gauge("topiceye_notifications_total", unread, "Total notifications")

    # ── Uptime ──
    uptime = time.monotonic() - _START_TIME
    gauge("topiceye_uptime_seconds", int(uptime), "Process uptime in seconds")

    # ── Slow queries (cumulative since startup) ──
    from app.core.slow_query import get_slow_count

    gauge("topiceye_slow_queries_total", get_slow_count(), "SQL queries exceeding slow query threshold (cumulative)")

    # ── LLM pre-filter low-signal counter (cumulative since startup) ──
    from app.services.llm_pre_filter import get_skip_count

    gauge("topiceye_low_signal_total", get_skip_count(), "Content items skipped from LLM queue by rule-based pre-filter (cumulative)")

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
