"""Metrics snapshot persistence — periodic write to SQLite + historical query.

Writes a row to ``metrics_snapshots`` every 60 seconds (driven by scheduler),
cleaned up after 7 days.  Enables historical trend analysis beyond the
30-minute in-memory ring buffer.
"""

from __future__ import annotations

import logging
import platform
import resource
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

from app.core.database import async_session
from app.core.sqlite_retry import retry_write_transaction
from app.models.metrics_snapshot import MetricsSnapshotRecord

logger = logging.getLogger(__name__)

# Retention: 7 days
_RETENTION_DAYS = 7


def _get_process_metrics() -> dict:
    """Collect process-level metrics via ``resource.getrusage``.

    macOS reports ru_maxrss in bytes; Linux reports it in KB.
    """
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    if platform.system() == "Darwin":
        rss_mb = rusage.ru_maxrss / (1024 * 1024)
    else:
        rss_mb = rusage.ru_maxrss / 1024
    return {
        "process_rss_mb": round(rss_mb, 1),
        "process_cpu_user_s": round(rusage.ru_utime, 2),
        "process_cpu_sys_s": round(rusage.ru_stime, 2),
    }


def _collect_snapshot_fields() -> dict:
    """Collect all metrics fields from the in-memory collector + process info."""
    from app.core.request_metrics import get_collector

    collector = get_collector()
    snap = collector.snapshot()

    proc = _get_process_metrics()

    # Slow queries
    slow_queries = 0
    try:
        from app.core.slow_query import get_slow_count
        slow_queries = get_slow_count()
    except Exception:
        pass

    http = snap.get("http", {})
    llm = snap.get("llm", {})
    db = snap.get("db_pool", {})
    http_lat = http.get("latency", {})
    llm_lat = llm.get("latency", {})

    return {
        "uptime_seconds": snap.get("uptime_seconds", 0),
        "http_total_requests": http.get("total_requests", 0),
        "http_total_errors_5xx": http.get("total_errors_5xx", 0),
        "http_error_rate": http.get("error_rate", 0),
        "http_p50": http_lat.get("p50", 0),
        "http_p95": http_lat.get("p95", 0),
        "http_p99": http_lat.get("p99", 0),
        "http_in_progress": snap.get("in_progress", 0),
        "http_rate_limit_hits": http.get("total_rate_limit_hits", 0),
        "llm_total_calls": llm.get("total_calls", 0),
        "llm_total_done": llm.get("total_done", 0),
        "llm_total_failed": llm.get("total_failed", 0),
        "llm_success_rate": llm.get("success_rate", 0),
        "llm_total_cost_usd": llm.get("total_cost_usd", 0),
        "llm_total_input_tokens": llm.get("total_input_tokens", 0),
        "llm_total_output_tokens": llm.get("total_output_tokens", 0),
        "llm_p50": llm_lat.get("p50", 0),
        "llm_p95": llm_lat.get("p95", 0),
        "llm_p99": llm_lat.get("p99", 0),
        "db_pool_checked_out": db.get("checked_out", 0),
        "db_pool_size": db.get("size", 0),
        "db_pool_utilization": db.get("utilization", 0),
        "slow_queries_total": slow_queries,
        **proc,
    }


async def persist_metrics_snapshot() -> str:
    """Write a single snapshot row to SQLite.

    Called by the scheduler every 60 seconds.  Failures are logged but
    never propagated — persistence must not block the scheduler.
    """
    try:
        fields = _collect_snapshot_fields()
    except Exception:
        logger.warning("metrics snapshot collection failed", exc_info=True)
        return "skipped"

    try:
        async with async_session() as db:
            record = MetricsSnapshotRecord(captured_at=datetime.now(UTC), **fields)

            async def _write():
                db.add(record)
                await db.flush()

            await retry_write_transaction(db, _write)
            await db.commit()
        return "ok"
    except Exception as exc:
        logger.warning("metrics snapshot persistence failed: %s", exc)
        return f"error: {exc}"


async def cleanup_old_snapshots() -> int:
    """Delete snapshots older than ``_RETENTION_DAYS`` days.

    Returns the number of deleted rows.
    """
    cutoff = datetime.now(UTC) - timedelta(days=_RETENTION_DAYS)
    try:
        async with async_session() as db:
            result = await db.execute(
                delete(MetricsSnapshotRecord).where(MetricsSnapshotRecord.captured_at < cutoff)
            )
            await db.commit()
            count = result.rowcount or 0
            if count:
                logger.info("Cleaned up %d old metrics snapshots (older than %d days)", count, _RETENTION_DAYS)
            return count
    except Exception as exc:
        logger.warning("metrics snapshot cleanup failed: %s", exc)
        return 0


async def query_history(hours: int = 1, limit: int = 500) -> list[dict]:
    """Query historical snapshot records.

    Parameters
    ----------
    hours : look-back window in hours (1–168, i.e. up to 7 days)
    limit : max rows to return (default 500, enough for 1h at 60s intervals)
    """
    since = datetime.now(UTC) - timedelta(hours=hours)
    try:
        async with async_session() as db:
            rows = await db.execute(
                select(MetricsSnapshotRecord)
                .where(MetricsSnapshotRecord.captured_at >= since)
                .order_by(MetricsSnapshotRecord.captured_at.asc())
                .limit(limit)
            )
            records = rows.scalars().all()
            return [
                {
                    "captured_at": r.captured_at.isoformat() if r.captured_at else None,
                    "uptime_seconds": r.uptime_seconds,
                    "http_total_requests": r.http_total_requests,
                    "http_total_errors_5xx": r.http_total_errors_5xx,
                    "http_error_rate": r.http_error_rate,
                    "http_p50": r.http_p50,
                    "http_p95": r.http_p95,
                    "http_p99": r.http_p99,
                    "http_in_progress": r.http_in_progress,
                    "http_rate_limit_hits": r.http_rate_limit_hits,
                    "llm_total_calls": r.llm_total_calls,
                    "llm_total_done": r.llm_total_done,
                    "llm_total_failed": r.llm_total_failed,
                    "llm_success_rate": r.llm_success_rate,
                    "llm_total_cost_usd": r.llm_total_cost_usd,
                    "llm_total_input_tokens": r.llm_total_input_tokens,
                    "llm_total_output_tokens": r.llm_total_output_tokens,
                    "llm_p50": r.llm_p50,
                    "llm_p95": r.llm_p95,
                    "llm_p99": r.llm_p99,
                    "db_pool_checked_out": r.db_pool_checked_out,
                    "db_pool_size": r.db_pool_size,
                    "db_pool_utilization": r.db_pool_utilization,
                    "process_rss_mb": r.process_rss_mb,
                    "process_cpu_user_s": r.process_cpu_user_s,
                    "process_cpu_sys_s": r.process_cpu_sys_s,
                    "slow_queries_total": r.slow_queries_total,
                }
                for r in records
            ]
    except Exception as exc:
        logger.warning("metrics history query failed: %s", exc)
        return []
