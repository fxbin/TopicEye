"""
信源抓取健康 API（per-source）。

不同于 /stats/jobs（看全局 @track_job 任务），本端点聚焦 source 自身的
抓取状态：每个 source 的 last_sync_at / status / sync_error /
下次预计抓取时间 / 最近抓取的新内容数。

数据来自 sources 表（不依赖 job_execution_logs）。
"""

from __future__ import annotations

from datetime import datetime, timezone, UTC

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import async_session
from app.models.content import ContentItem
from app.models.source import Source, SourceStatus

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
    async with async_session() as db:
        # per-source 内容统计（子查询避免 N+1）
        total_subq = select(ContentItem.source_id, func.count().label("cnt")).group_by(ContentItem.source_id).subquery()
        recent_cutoff = datetime.now(UTC).toordinal()  # placeholder

        stmt = select(
            Source,
            func.coalesce(total_subq.c.cnt, 0).label("content_count"),
        ).outerjoin(total_subq, total_subq.c.source_id == Source.id)
        if status_filter:
            stmt = stmt.where(Source.status == status_filter)
        stmt = stmt.order_by(desc(Source.last_sync_at)).limit(limit)

        rows = (await db.execute(stmt)).all()

        # 最近 24h 内容数（单独查，避免复杂 JOIN）
        now = datetime.now(UTC)
        from datetime import timedelta

        recent_cutoff_dt = now - timedelta(hours=24)

        sources_health = []
        for source, content_count in rows:
            # recent count per source
            recent_count = (
                await db.scalar(
                    select(func.count())
                    .select_from(ContentItem)
                    .where(
                        ContentItem.source_id == source.id,
                        ContentItem.crawled_at >= recent_cutoff_dt,
                    )
                )
                or 0
            )

            last_sync_aware = source.last_sync_at
            last_sync_ago = (
                int((now - last_sync_aware.replace(tzinfo=UTC)).total_seconds()) if last_sync_aware else None
            )

            interval_seconds = (source.fetch_interval_minutes or 60) * 60
            next_sync_in = None
            if last_sync_ago is not None:
                next_sync_in = max(0, interval_seconds - last_sync_ago)

            # stale SYNCING 判定（> 3 × SOURCE_SYNC_TIMEOUT_SECONDS）
            from app.core.config import settings

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

    # 汇总
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
