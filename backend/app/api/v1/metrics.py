"""
Prometheus 兼容的 /metrics 端点。

暴露 TopicEye 的关键运行指标，可被 Prometheus / Grafana / VictoriaMetrics
抓取。无需第三方库——直接输出 Prometheus text format。

指标覆盖（业务数据层）：
- topiceye_sources_total{status}: 按 status 分的 source 数
- topiceye_content_total{status}: 按 status 分的内容数
- topiceye_content_recent_24h: 最近 24h 新增内容数
- topiceye_analyses_total: 分析总数
- topiceye_job_runs_total{status}: job 运行数（从 job_execution_logs）
- topiceye_uptime_seconds: 进程运行时间
- topiceye_slow_queries_total: 慢查询累计计数
- topiceye_low_signal_total: 预过滤跳过的低信号内容累计计数

指标覆盖（HTTP 请求可观测性层 — 来自 RequestMetricsCollector）：
- topiceye_http_requests_total{method,path,status}: HTTP 请求总数
- topiceye_http_request_duration_seconds{method,path}: 请求延迟 histogram
- topiceye_http_requests_in_progress: 当前在途请求数
- topiceye_http_rate_limit_hits_total{path}: 限流命中次数
- topiceye_http_errors_total{method,path,status_class}: 5xx 错误数

指标覆盖（LLM 调用聚合层 — 来自 RequestMetricsCollector）：
- topiceye_llm_calls_total{scene,status}: LLM 调用总数
- topiceye_llm_call_duration_seconds{scene}: LLM 调用延迟 histogram
- topiceye_llm_tokens_total{scene,direction}: LLM token 用量
- topiceye_llm_cost_total{scene}: LLM 累计成本 (USD)

指标覆盖（数据库连接池层）：
- topiceye_db_pool_size{pool}: 连接池配置大小
- topiceye_db_pool_checked_out{pool}: 当前已借出连接数
- topiceye_db_pool_overflow{pool}: 当前溢出连接数
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

    # ── HTTP 请求指标（来自 RequestMetricsCollector 内存计数器）──
    from app.core.request_metrics import get_collector

    collector = get_collector()
    lines.extend(collector.render_prometheus())

    # ── 数据库连接池指标 ──
    from app.core.database import engine

    try:
        pool = engine.sync_engine.pool
        # SQLAlchemy AsyncEngine wraps a sync pool; .status() returns (size, checked_in, checked_out, overflow)
        pool_status = pool.status()
        if isinstance(pool_status, tuple) and len(pool_status) >= 4:
            size, _checked_in, checked_out, overflow = pool_status[:4]
            gauge("topiceye_db_pool_size", size, "DB connection pool configured size", {"pool": "primary"})
            gauge("topiceye_db_pool_checked_out", checked_out, "DB connections currently checked out", {"pool": "primary"})
            gauge("topiceye_db_pool_overflow", overflow, "DB connections currently in overflow", {"pool": "primary"})
            collector.update_db_pool_snapshot(checked_out, size)
    except Exception as exc:
        gauge("topiceye_db_pool_error", 1, "DB pool metrics collection error", {"pool": "primary"})
        # 不阻断 /metrics 输出
        import logging
        logging.getLogger(__name__).debug("DB pool metrics failed: %s", exc)

    return Response(
        content="\n".join(lines) + "\n",
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


# ── JSON 快照端点（供内置监控大盘消费，非 Prometheus 格式）──


@router.get("/snapshot")
async def metrics_snapshot():
    """JSON 格式的实时指标快照 + 时间序列数据。

    供内置监控大盘（/dashboard 页面）轮询消费，返回：
    - 当前累计计数器快照（HTTP / LLM / DB 连接池）
    - 最近 30 分钟时间序列数据（每 10s 一个采样点）
    - LLM 熔断器状态
    - 系统健康状态摘要
    """
    from app.core.request_metrics import get_collector

    collector = get_collector()
    # 轮询驱动采样：每次被请求时检查是否该追加一个时间序列点
    collector.maybe_sample_timeseries()

    snapshot = collector.snapshot()
    timeseries = collector.timeseries()

    # LLM 熔断器状态
    breaker_status: dict = {}
    try:
        from app.services.llm.circuit_breaker import get_llm_circuit_breaker

        breaker_status = get_llm_circuit_breaker().status()
    except Exception:
        pass

    # 慢查询计数
    slow_queries = 0
    try:
        from app.core.slow_query import get_slow_count
        slow_queries = get_slow_count()
    except Exception:
        pass

    # LLM 响应缓存命中率
    cache_status: dict = {}
    try:
        from app.services.llm.response_cache import get_llm_cache
        cache_status = get_llm_cache().status()
    except Exception:
        pass

    return {
        "snapshot": snapshot,
        "timeseries": timeseries,
        "circuit_breaker": breaker_status,
        "slow_queries": slow_queries,
        "llm_cache": cache_status,
    }
