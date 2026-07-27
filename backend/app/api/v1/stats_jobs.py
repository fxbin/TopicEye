"""
抓取/调度任务执行统计 API（job_execution_logs 聚合）。

不走 DuckDB —— job_execution_logs 在 OLTP DB（PG/SQLite），
和 stats.py 的 DuckDB 分析路径独立。复用 json_cache 做轻量缓存。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import async_session
from app.repositories.job_execution_log_repo import JobExecutionLogRepository
from app.services.json_cache import get_cached_json, set_cached_json

router = APIRouter(
    prefix="/stats/jobs",
    tags=["stats"],
    dependencies=[Depends(get_current_user)],
)


def _cache_key(days: int, job_key: str | None) -> str:
    return f"stats:jobs:{days}:{job_key or 'all'}"


def _miss_response(cache_key: str, payload: dict) -> Response:
    content = set_cached_json(cache_key, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Stats-Cache": "MISS"},
    )


@router.get("")
async def get_job_stats(
    days: int = Query(7, ge=1, le=90),
    job_key: str | None = Query(None, description="按 job_key 过滤，可选"),
):
    """抓取/调度任务执行统计。

    返回:
    - period: 查询时间范围
    - totals: 总运行数、成功率、状态分布、耗时均值
    - by_status: 按 status 分组的计数
    - by_job_key: 每个 job_key 的运行数、成功率、最近状态
    - recent_failures: 最近 10 条失败/超时记录
    """
    cache_key = _cache_key(days, job_key)
    cached = get_cached_json(cache_key, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "X-Stats-Cache": "HIT",
                "X-Stats-Cache-Age-Ms": str(int(age_seconds * 1000)),
            },
        )

    payload = await _build_job_stats_payload(days=days, job_key=job_key)
    return _miss_response(cache_key, payload)


async def _build_job_stats_payload(*, days: int, job_key: str | None) -> dict:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    end = datetime.now(UTC)

    async with async_session() as db:
        repo = JobExecutionLogRepository(db)

        # ── by_status ──
        status_rows = await repo.count_by_status_since(cutoff=cutoff, job_key=job_key)
        by_status = {row[0]: int(row[1]) for row in status_rows}

        # ── duration aggregates ──
        dur_row = await repo.aggregate_duration_since(cutoff=cutoff, job_key=job_key)
        avg_duration_ms = int(dur_row.avg_dur) if dur_row.avg_dur else 0
        max_duration_ms = int(dur_row.max_dur) if dur_row.max_dur else 0

        # ── by_job_key (runs + success_count) ──
        per_key_rows = await repo.count_runs_per_job_key_since(cutoff=cutoff, job_key=job_key)

        by_job_key: list[dict] = []
        for r_job_key, r_runs in per_key_rows:
            success_count = await repo.count_success_for_job_key(
                job_key=r_job_key, cutoff=cutoff
            )
            last = await repo.get_last_run_for_job_key(r_job_key)
            by_job_key.append(
                {
                    "job_key": r_job_key,
                    "runs": int(r_runs),
                    "success_count": success_count,
                    "success_rate": round(success_count / int(r_runs), 4) if r_runs else 0.0,
                    "avg_duration_ms": 0,  # populated below in aggregate query
                    "last_status": last[0] if last else None,
                    "last_run_at": last[1].isoformat() if last and last[1] else None,
                    "last_duration_ms": int(last[2]) if last and last[2] else None,
                    "last_error": (last[3] or "")[:500] if last and last[3] else None,
                }
            )

        # ── per-job_key avg_duration (single aggregate query) ──
        if per_key_rows:
            avg_per_key_rows = await repo.aggregate_avg_duration_per_job_key_since(cutoff=cutoff)
            avg_lookup = {row[0]: int(row[1]) if row[1] else 0 for row in avg_per_key_rows}
            for entry in by_job_key:
                entry["avg_duration_ms"] = avg_lookup.get(entry["job_key"], 0)

        # ── recent failures ──
        failure_rows = await repo.list_recent_failures_since(
            cutoff=cutoff, job_key=job_key, limit=10
        )
        recent_failures = [
            {
                "job_key": row[0],
                "status": row[1],
                "started_at": row[2].isoformat() if row[2] else None,
                "duration_ms": int(row[3]) if row[3] else None,
                "error_message": (row[4] or "")[:500] if row[4] else None,
            }
            for row in failure_rows
        ]

    total_runs = sum(by_status.values())
    success_total = by_status.get("SUCCESS", 0)
    return {
        "period": {
            "days": days,
            "start": cutoff.isoformat(),
            "end": end.isoformat(),
        },
        "totals": {
            "total_runs": total_runs,
            "success_count": success_total,
            "failed_count": by_status.get("FAILED", 0),
            "timeout_count": by_status.get("TIMEOUT", 0),
            "skipped_count": by_status.get("SKIPPED", 0),
            "running_count": by_status.get("RUNNING", 0),
            "success_rate": round(success_total / total_runs, 4) if total_runs else 0.0,
            "avg_duration_ms": avg_duration_ms,
            "max_duration_ms": max_duration_ms,
        },
        "by_status": [{"status": k, "count": v} for k, v in sorted(by_status.items())],
        "by_job_key": by_job_key,
        "recent_failures": recent_failures,
    }
