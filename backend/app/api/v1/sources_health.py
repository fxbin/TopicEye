"""
信源抓取健康 API（per-source）。

不同于 /stats/jobs（看全局 @track_job 任务），本端点聚焦 source 自身的
抓取状态：每个 source 的 last_sync_at / status / sync_error /
下次预计抓取时间 / 最近抓取的新内容数。

数据来自 sources 表（不依赖 job_execution_logs）。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, UTC

from fastapi import APIRouter, Depends, Query

from app.api.v1.auth import get_current_admin_user
from app.core.config import settings
from app.core.database import async_session
from app.models.source import SourceStatus
from app.repositories.source_health_repo import SourceHealthRepository

router = APIRouter(
    prefix="/stats/sources-health",
    tags=["stats"],
    dependencies=[Depends(get_current_admin_user)],
)


@router.get("")
async def get_sources_health(
    status_filter: str | None = Query(None, alias="status", description="按 status 过滤"),
    limit: int = Query(100, ge=1, le=500),
):
    """每个信源的抓取健康状态。

    返回字段：
    - id / name / source_type / platform / enabled / fetch_interval_minutes
    - status: active / syncing / error / disabled
    - last_sync_at / last_sync_ago_seconds
    - sync_error: 最近错误（截 300 字符）
    - next_sync_in_seconds: 预计下次抓取（基于 interval + last_sync）
    - content_count: 该 source 的内容总数
    - recent_content_count: 最近 24h 新增内容数
    - is_stale: 是否卡 SYNCING 超过 lease（health 风险标记）
    """
    now = datetime.now(UTC)
    recent_cutoff_dt = now - timedelta(hours=24)

    async with async_session() as db:
        repo = SourceHealthRepository(db)
        rows = await repo.list_sources_with_content_count(status_filter, limit)

        sources_health = []
        for source, content_count in rows:
            recent_count = await repo.count_recent_content(source.id, recent_cutoff_dt)

            last_sync_aware = source.last_sync_at
            last_sync_ago = (
                int((now - last_sync_aware.replace(tzinfo=UTC)).total_seconds()) if last_sync_aware else None
            )

            interval_seconds = (source.fetch_interval_minutes or 60) * 60
            next_sync_in = None
            if last_sync_ago is not None:
                next_sync_in = max(0, interval_seconds - last_sync_ago)

            stale_threshold = int(settings.SOURCE_SYNC_TIMEOUT_SECONDS) * 3
            is_stale = (
                source.status == SourceStatus.SYNCING and last_sync_ago is not None and last_sync_ago > stale_threshold
            )

            sources_health.append(
                {
                    "id": source.id,
                    "name": source.name,
                    "source_type": source.source_type,
                    "platform": source.platform,
                    "enabled": source.enabled,
                    "fetch_interval_minutes": source.fetch_interval_minutes,
                    "status": source.status,
                    "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
                    "last_sync_ago_seconds": last_sync_ago,
                    "next_sync_in_seconds": next_sync_in,
                    "sync_error": (source.sync_error or "")[:300] or None,
                    "content_count": content_count,
                    "recent_content_count_24h": recent_count,
                    "is_stale": is_stale,
                }
            )

    total = len(sources_health)
    by_status = {}
    for s in sources_health:
        by_status[s["status"]] = by_status.get(s["status"], 0) + 1
    stale_count = sum(1 for s in sources_health if s["is_stale"])

    return {
        "total": total,
        "by_status": by_status,
        "stale_syncing_count": stale_count,
        "sources": sources_health,
    }
