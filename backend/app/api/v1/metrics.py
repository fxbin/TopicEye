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

指标覆盖（LLM 模型池运行层 — 来自 LlmPoolMetrics，MP-P0-T3）：
- topiceye_llm_pool_inflight{scope}: 当前在途调用数（gauge）
- topiceye_llm_pool_max_active{scope}: 历史最大在途（gauge）
- topiceye_llm_pool_admitted_total{scope}: 已放行调用累计（counter）
- topiceye_llm_pool_queue_wait_seconds_total{scope}: 排队等待累计秒（counter）
- topiceye_llm_pool_rate_limit_wait_seconds_total{scope}: 限流等待累计秒（counter）
- topiceye_llm_pool_circuit_events_total{scope,event}: 熔断事件累计（counter）
- topiceye_analysis_pending_total: 仍可被分析队列领取的内容数（积压深度）

scope 形如 route:{routing_group}|channel:{channel_or_model}|scene:{scene}，
为低基数聚合键，不包含 prompt、密钥或内容 id。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, Response

from app.core.database import async_session
from app.repositories.llm_call_log_repo import LlmCallLogRepository
from app.repositories.content_repo import ContentRepo
from app.repositories.metrics_query_repo import MetricsQueryRepository

router = APIRouter(prefix="/metrics", tags=["metrics"])

_START_TIME = time.monotonic()


def _render_llm_pool_metrics(
    pool_snapshot: dict[str, dict[str, float | int]],
) -> list[str]:
    """把 LlmPoolMetrics.snapshot() 渲染为 Prometheus text format 行。

    scope 是低基数聚合键（route|channel|scene），不含敏感字段；这里仍对值做
    标签转义以遵守 Prometheus label 规范（双引号、反斜杠、换行）。
    """
    if not pool_snapshot:
        return []

    out: list[str] = []

    def _esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")

    def _emit(name: str, metric_type: str, value: float | int, help_text: str, labels: dict[str, str]):
        out.append(f"# HELP {name} {help_text}")
        out.append(f"# TYPE {name} {metric_type}")
        label_str = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        # 整数计数器保持整数表示，避免浮点显示
        out.append(f"{name}{{{label_str}}} {value:g}")

    # 按 scope 排序，保证抓取输出稳定（便于 diff / 测试断言）。
    for scope in sorted(pool_snapshot):
        data = pool_snapshot[scope]
        if "active" in data:
            _emit(
                "topiceye_llm_pool_inflight",
                "gauge",
                data["active"],
                "LLM calls currently in-flight per pool scope",
                {"scope": scope},
            )
        if "max_active" in data:
            _emit(
                "topiceye_llm_pool_max_active",
                "gauge",
                data["max_active"],
                "High-water mark of in-flight LLM calls per pool scope",
                {"scope": scope},
            )
        if "admitted" in data:
            _emit(
                "topiceye_llm_pool_admitted_total",
                "counter",
                data["admitted"],
                "LLM calls admitted per pool scope (cumulative)",
                {"scope": scope},
            )
        if "queue_wait_seconds" in data:
            _emit(
                "topiceye_llm_pool_queue_wait_seconds_total",
                "counter",
                data["queue_wait_seconds"],
                "Cumulative seconds spent waiting for a completion slot",
                {"scope": scope},
            )
        if "rate_limit_wait_seconds" in data:
            _emit(
                "topiceye_llm_pool_rate_limit_wait_seconds_total",
                "counter",
                data["rate_limit_wait_seconds"],
                "Cumulative seconds spent waiting on RPM/token admission",
                {"scope": scope},
            )
        # 熔断事件计数以 circuit_{event}_total 形式存储在 scope 字典里。
        for key, count in data.items():
            if key.startswith("circuit_") and key.endswith("_total"):
                event = key[len("circuit_") : -len("_total")]
                _emit(
                    "topiceye_llm_pool_circuit_events_total",
                    "counter",
                    count,
                    "LLM pool circuit-breaker events (cumulative)",
                    {"scope": scope, "event": event},
                )

    return out


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
        repo = MetricsQueryRepository(db)

        # ── Sources by status ──
        for status, count in await repo.count_sources_by_status():
            gauge("topiceye_sources_total", count, "Sources by status", {"status": status})

        # ── Content by status ──
        for status, count in await repo.count_content_by_status():
            gauge("topiceye_content_total", count, "Content items by status", {"status": status})

        # ── Recent content (24h) ──
        cutoff = now - timedelta(hours=24)
        recent = await repo.count_recent_content(cutoff)
        gauge("topiceye_content_recent_24h", recent, "Content items crawled in last 24h")

        # ── Analyses total ──
        analyses = await repo.count_analyses()
        gauge("topiceye_analyses_total", analyses, "Total AI analyses")

        # ── Job runs by status (last 24h) ──
        for status, count in await repo.count_job_runs_by_status_since(cutoff):
            gauge("topiceye_job_runs_total", count, "Job runs in last 24h by status", {"status": status})

        # ── Notifications unread ──
        unread = await repo.count_notifications()
        gauge("topiceye_notifications_total", unread, "Total notifications")

        # ── Analysis backlog depth（模型池积压：仍可被领取的待分析内容数）──
        # 复用 list_pending_for_analysis / claim_pending_analysis_jobs 同一资格谓词。
        pending = await ContentRepo(db).count_pending_for_analysis()
        gauge(
            "topiceye_analysis_pending_total",
            pending,
            "Content items still claimable by the analysis queue (backlog depth)",
        )

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

    # ── LLM 模型池运行指标（进程内存，无 DB 访问）──
    # LlmPoolMetrics 已记录 inflight / admitted / queue wait / 熔断事件，
    # 这里只做 Prometheus 文本导出。scope 形如 route:{group}|channel:{x}|scene:{y}。
    try:
        from app.services.llm._rate_limit import get_llm_pool_metrics

        pool_snapshot = get_llm_pool_metrics()
        lines.extend(_render_llm_pool_metrics(pool_snapshot))
    except Exception as exc:  # noqa: BLE001 — 指标导出不得阻断 /metrics
        import logging

        logging.getLogger(__name__).debug("LLM pool metrics export failed: %s", exc)

    # ── 数据库连接池指标 ──
    from app.core.database import engine

    try:
        pool = engine.sync_engine.pool
        size = pool.size()
        checked_out = pool.checkedout()
        overflow = pool.overflow()
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

    # 采集 DB 连接池指标（同步到 collector，供 snapshot / timeseries 使用）
    # 避免依赖 /metrics Prometheus 端点被单独请求才有数据
    try:
        from app.core.database import engine

        pool = engine.sync_engine.pool
        size = pool.size()
        checked_out = pool.checkedout()
        collector.update_db_pool_snapshot(checked_out, size)
    except Exception:
        pass

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

    # 进程级指标（内存 / CPU）
    process: dict = {}
    try:
        from app.services.metrics_persistence import _get_process_metrics
        process = _get_process_metrics()
    except Exception:
        pass

    # LLM 模型池运行指标（inflight / admitted / queue wait，MP-P0-T3）
    llm_pool: dict = {}
    try:
        from app.services.llm._rate_limit import get_llm_pool_metrics

        llm_pool = get_llm_pool_metrics()
    except Exception:
        pass

    # 分析积压深度（仍可被队列领取的内容数）
    analysis_pending = 0
    try:
        async with async_session() as db:
            analysis_pending = await ContentRepo(db).count_pending_for_analysis()
    except Exception:
        pass

    return {
        "snapshot": snapshot,
        "timeseries": timeseries,
        "circuit_breaker": breaker_status,
        "slow_queries": slow_queries,
        "llm_cache": cache_status,
        "process": process,
        "llm_pool": llm_pool,
        "analysis_pending": analysis_pending,
    }


# ── 历史快照端点（从 SQLite 查询持久化的指标历史）──


@router.get("/history")
async def metrics_history(
    hours: int = Query(1, ge=1, le=168, description="Look-back window in hours (max 7 days)"),
    limit: int = Query(500, ge=1, le=2000, description="Max rows to return"),
):
    """Historical metrics snapshots from SQLite.

    Returns persisted snapshot records for the given look-back window.
    Useful for trend charts beyond the 30-minute in-memory ring buffer.
    """
    from app.services.metrics_persistence import query_history

    records = await query_history(hours=hours, limit=limit)
    return {"hours": hours, "count": len(records), "records": records}


# ── 应用日志端点（从内存 ring buffer 查询）──


@router.get("/logs")
async def metrics_logs(
    level: str = Query("ALL", description="Filter by log level (ALL/DEBUG/INFO/WARNING/ERROR/CRITICAL)"),
    limit: int = Query(200, ge=1, le=1000, description="Max entries to return"),
):
    """Recent application logs from the in-memory ring buffer.

    Entries are returned newest-first.  Buffer capacity is 1000 entries.
    """
    from app.core.log_ringbuffer import get_ring_buffer_handler

    handler = get_ring_buffer_handler()
    entries = handler.get_entries(level=level.upper() if level != "ALL" else None, limit=limit)
    summary = handler.get_summary()
    return {"entries": entries, "summary": summary}


# ── LLM 调用日志端点（从 SQLite 查询 llm_call_logs 表）──


@router.get("/llm-logs")
async def llm_call_logs(
    status: str = Query("ALL", description="Filter by status (ALL/DONE/FAILED)"),
    limit: int = Query(50, ge=1, le=500, description="Max entries to return"),
):
    """Recent LLM call logs from the ``llm_call_logs`` table.

    When ``status=FAILED`` is specified, returns only failed calls —
    useful for diagnosing LLM errors from the dashboard.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=24)
    async with async_session() as db:
        repo = LlmCallLogRepository(db)
        rows = await repo.list_recent(status=status, cutoff=cutoff, limit=limit)

    return {
        "count": len(rows),
        "logs": [
            {
                "request_id": r.request_id,
                "scene": r.scene,
                "model": r.actual_model or "unknown",
                "status": r.status,
                "error": (r.error_message or "")[:300],
                "duration_ms": r.duration_ms,
                "input_tokens": r.input_tokens,
                "output_tokens": r.output_tokens,
                "cost_usd": round(r.total_cost, 6) if r.total_cost else 0,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }
