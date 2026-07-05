"""
APScheduler-based periodic task scheduler.

Per-source scheduling:
    - Each enabled source gets its own IntervalTrigger job.
    - Interval is read from source.fetch_interval_minutes (default 60 min).
    - A rescan job runs every 10 minutes to pick up new / updated sources.
    - cleanup_old_content: daily at 03:00.

All DB access goes through Repository layer — no raw SQL here.

Job tracking:
    - Every scheduled job is wrapped with @track_job decorator.
    - Execution records go to job_execution_logs table.
    - Task configs are auto-registered to scheduled_jobs table.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.database import async_session
from app.repositories.content_repo import ContentRepo
from app.repositories.source_repo import SourceRepository
from app.services.analysis import analyze_batch_concurrent
from app.services.content_pipeline import ingest_from_source
from app.services.job_tracker import track_job
# Post-sync pipeline functions are extracted to a separate module for module size.
# Re-export here so existing `from app.scheduler import _request_post_sync_pipeline` keeps working.
from app._post_sync_pipeline import (
    _request_post_sync_pipeline,  # noqa: F401 — re-export
    _clear_post_sync_task,  # noqa: F401
    _run_post_sync_pipeline,  # noqa: F401
    _run_post_sync_pipeline_once,  # noqa: F401
    _drain_pending_analysis,  # noqa: F401
    _release_inflight_analysis_claims,  # noqa: F401
    _get_post_sync_lock,  # noqa: F401
)

logger = logging.getLogger(__name__)

# Semaphore to limit concurrent DB write tasks — SQLite single-writer constraint.
_sync_semaphore: asyncio.Semaphore | None = None
_sync_semaphore_limit: int | None = None
# _post_sync_lock / _post_sync_task / _post_sync_rerun_requested 已外迁到 app._post_sync_pipeline


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _source_sync_concurrency() -> int:
    return _positive_int(getattr(settings, "SOURCE_SYNC_WORKER_CONCURRENCY", 3), 3)


def _post_sync_analysis_batch_size() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_ANALYSIS_BATCH_SIZE", 10), 10)


def _post_sync_analysis_time_budget_seconds() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_ANALYSIS_TIME_BUDGET_SECONDS", 520), 520)


def _post_sync_min_remaining_seconds() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_MIN_REMAINING_SECONDS", 90), 90)


def _get_semaphore() -> asyncio.Semaphore:
    global _sync_semaphore, _sync_semaphore_limit
    limit = _source_sync_concurrency()
    if _sync_semaphore is None or _sync_semaphore_limit != limit:
        _sync_semaphore = asyncio.Semaphore(limit)
        _sync_semaphore_limit = limit
    return _sync_semaphore


def _get_post_sync_lock() -> asyncio.Lock:
    global _post_sync_lock
    if _post_sync_lock is None:
        _post_sync_lock = asyncio.Lock()
    return _post_sync_lock


scheduler = AsyncIOScheduler(
    timezone="Asia/Shanghai",
    job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 120},
)


# ── Scheduled jobs ────────────────────────────────────────────────────


@track_job(
    "sync_and_analyze",
    name="全量信源同步+分析",
    timeout=600,
    description="同步所有启用的信源，自动分析新内容，聚类+趋势快照",
)
async def sync_and_analyze() -> None:
    """Legacy: sync all enabled sources, then auto-analyze new pending content."""
    logger.info("Scheduler: sync_and_analyze started")

    # ── Phase 1: Sync sources ──
    async with async_session() as db:
        source_repo = SourceRepository(db)
        sources = await source_repo.get_enabled_sources()

        for source in sources:
            try:
                stats = await ingest_from_source(source, db)
                logger.info("Scheduler: synced source '%s' — %s", source.name, stats)
            except Exception:
                logger.exception("Scheduler: failed to sync source '%s' (id=%d)", source.name, source.id)
            await db.commit()

    logger.info("Scheduler: sync finished (%d sources)", len(sources))

    # ── Phase 2: Auto-analyze pending content ──
    analysis_stats = await _drain_pending_analysis()

    if analysis_stats["attempted"] == 0:
        logger.info("Scheduler: no pending content to analyze")
        return

    if analysis_stats["remaining"]:
        logger.info(
            "Scheduler: pending backlog remains after analysis drain — %s; clustering deferred",
            analysis_stats,
        )
        return

    # ── Phase 3: Cluster + dedup ──
    try:
        async with async_session() as db:
            from app.services.topic_clustering import cluster_and_dedup_with_lease

            stats, claimed = await cluster_and_dedup_with_lease(db, trigger_type="scheduler")
        if claimed:
            logger.info("Scheduler: clustering done — %s", stats)
        else:
            logger.info("Scheduler: clustering skipped because another run holds the lease")
    except Exception:
        logger.exception("Scheduler: clustering failed")

    # ── Phase 4: Trend snapshot ──
    try:
        async with async_session() as db:
            from app.services.trends import snapshot_daily_trends

            stats = await snapshot_daily_trends(db)
            await db.commit()
        logger.info("Scheduler: trend snapshot done — %s", stats)
    except Exception:
        logger.exception("Scheduler: trend snapshot failed")


@track_job(
    "cleanup_old_content", name="清理90天前的待处理内容", timeout=120, description="删除 pending 状态超过90天的内容"
)
async def cleanup_old_content() -> None:
    """Remove pending content older than 90 days."""
    logger.info("Scheduler: cleanup_old_content started")
    cutoff = datetime.now(UTC) - timedelta(days=90)

    async with async_session() as db:
        content_repo = ContentRepo(db)
        removed = await content_repo.delete_old_pending(cutoff_days=90)
        await db.commit()
        logger.info("Scheduler: cleanup_old_content removed %d old pending items", removed)
        return f"removed={removed}"


@track_job(
    "cleanup_old_notifications",
    name="清理30天前的站内通知",
    timeout=60,
    description="删除30天前的 notifications（CASCADE 自动清 notification_reads）",
)
async def cleanup_old_notifications() -> None:
    """Remove notifications older than 30 days.

    NotificationRead rows are cleaned automatically via ON DELETE CASCADE.
    """
    logger.info("Scheduler: cleanup_old_notifications started")
    try:
        from app.services.notification_service import cleanup_old_notifications as _cleanup

        async with async_session() as db:
            removed = await _cleanup(days=30)
            await db.commit()
        logger.info("Scheduler: cleanup_old_notifications removed %d records", removed)
        return f"removed={removed}"
    except Exception:
        logger.exception("Scheduler: cleanup_old_notifications failed")


@track_job("sync_trending", name="趋势雷达数据同步", timeout=120, description="每30分钟同步所有趋势信源数据")
async def _sync_all_trending() -> None:
    """Sync all trending sources (lightweight, no LLM)."""
    from app.services.trending_pipeline import sync_all_trending

    try:
        async with async_session() as db:
            results = await sync_all_trending(db)
        total = sum(r.get("fetched", 0) for r in results.values())
        logger.info("Scheduler: trending sync done — %d items from %d sources", total, len(results))
        return f"fetched={total}, sources={len(results)}"
    except Exception:
        logger.exception("Scheduler: trending sync failed")


async def _sync_single_source(source_id: int) -> None:
    """Job handler: sync one source by ID.

    Keep this job narrow: one source fetch + one source status update. Global
    analysis/clustering runs on its own throttled schedule so many source jobs
    do not stampede SQLite with heavy post-sync writes.
    """
    sem = _get_semaphore()
    async with sem, async_session() as db:
        from app.repositories.source_repo import SourceRepository

        source_repo = SourceRepository(db)
        source = await source_repo.claim_sync(
            source_id,
            lease_seconds=int(settings.SOURCE_SYNC_TIMEOUT_SECONDS),
        )
        await db.commit()
        if not source or not source.enabled:
            logger.debug("Source id=%d skipped (not found, disabled, or sync lease active)", source_id)
            return
        try:
            stats = await ingest_from_source(source, db)
            await db.commit()
            logger.info("Scheduler: source '%s' synced — %s", source.name, stats)
            _request_post_sync_pipeline(stats)
        except Exception:
            logger.exception("Scheduler: failed to sync source id=%d", source_id)
            await db.rollback()


async def _rescan_sources() -> None:
    """Every 10 minutes: sync scheduler job list with enabled sources from DB.

    Also self-heals sources stuck in SYNCING past their lease — this happens
    when a sync job was killed (SIGTERM / crash) after claim_sync committed
    status=SYNCING but before ingest completed.

    Self-heal 流程:
    1. UPDATE DB 把 stale SYNCING 重置为 ACTIVE(脱离死锁状态)
    2. scheduler.add_job(..., next_run_time=now) 立即重跑这些 source
       (避免只 reset 不重试,导致数据持续真空)
    """
    healed_source_ids: list[int] = []
    async with async_session() as db:
        # ── Self-heal: reset stale SYNCING sources ──
        stale_cutoff = datetime.now(UTC) - timedelta(seconds=int(settings.SOURCE_SYNC_TIMEOUT_SECONDS) * 3)
        from sqlalchemy import update as sa_update

        from app.models.source import Source, SourceStatus

        heal_result = await db.execute(
            sa_update(Source)
            .where(
                Source.status == SourceStatus.SYNCING,
                Source.last_sync_at < stale_cutoff,
            )
            .values(status=SourceStatus.ACTIVE, sync_error="auto-reset from stale SYNCING")
            .returning(Source.id)
        )
        healed_source_ids = [row[0] for row in heal_result.fetchall()]
        if healed_source_ids:
            await db.commit()
            logger.warning(
                "Scheduler: self-healed %d source(s) stuck in SYNCING (>3x lease): ids=%s",
                len(healed_source_ids),
                healed_source_ids,
            )

        # ── Alert: sources with status=ERROR (连续失败) ──
        try:
            from app.services.alerting import alert_source_failures

            error_sources = (
                await db.execute(
                    select(Source.name, Source.source_type, Source.sync_error).where(
                        Source.status == SourceStatus.ERROR, Source.enabled.is_(True)
                    )
                )
            ).all()
            if error_sources:
                await alert_source_failures(
                    [{"name": r[0], "source_type": r[1], "error": r[2] or ""} for r in error_sources]
                )
        except Exception:
            logger.debug("Source failure alert skipped (non-fatal)", exc_info=True)

        source_repo = SourceRepository(db)
        sources = await source_repo.get_enabled_sources()

    current_job_ids = {job.id for job in scheduler.get_jobs()}
    source_job_prefix = "source_sync_"
    db_source_ids = {f"{source_job_prefix}{s.id}" for s in sources}

    for job_id in current_job_ids:
        if job_id.startswith(source_job_prefix) and job_id not in db_source_ids:
            scheduler.remove_job(job_id)
            logger.info("Scheduler: removed job %s (source disabled)", job_id)

    # ── Self-heal retry: 立即重跑刚被 heal 的 source,避免数据持续真空 ──
    # 用 next_run_time=now 让 add_job 不走"下次 interval"等待,
    # 直接进入队列。run_date 已弃用,DateTrigger 替代。
    if healed_source_ids:
        for source_id in healed_source_ids:
            job_id = f"{source_job_prefix}{source_id}"
            existing = scheduler.get_job(job_id)
            if existing:
                # 复用既存 IntervalTrigger job,只把 next_run_time 改 now。
                # 不要 add 新 DateTrigger job — 下方 rescan 主循环 (line 547)
                # 会扫 job.trigger.interval,DateTrigger 没有 interval 属性会 AttributeError。
                try:
                    scheduler.modify_job(job_id, next_run_time=datetime.now(UTC))
                    logger.info("Scheduler: heal-retry rescheduled source %d (now)", source_id)
                except Exception as e:
                    logger.warning(
                        "Scheduler: failed to reschedule heal-retry for source %d: %s",
                        source_id,
                        e,
                    )
            else:
                # 没有既存 job(冷启动场景),下方 rescan 主循环会 add_job 加上
                logger.info(
                    "Scheduler: source %d healed, will be added by main rescan loop",
                    source_id,
                )

    for source in sources:
        job_id = f"{source_job_prefix}{source.id}"
        interval_minutes = _normalize_source_interval(source.fetch_interval_minutes)
        next_run_time = _next_source_run_time(source.last_sync_at, interval_minutes)

        existing = scheduler.get_job(job_id)
        if existing:
            existing_interval = int(existing.trigger.interval.total_seconds() // 60)
            if existing_interval != interval_minutes:
                scheduler.reschedule_job(job_id, trigger=IntervalTrigger(minutes=interval_minutes))
                scheduler.modify_job(job_id, next_run_time=next_run_time)
                logger.info("Scheduler: updated job %s interval to %d min", job_id, interval_minutes)
            elif _source_job_is_overdue(existing, next_run_time):
                scheduler.modify_job(job_id, next_run_time=next_run_time)
                logger.info("Scheduler: advanced overdue job %s to %s", job_id, next_run_time)
        else:
            scheduler.add_job(
                _sync_single_source,
                trigger=IntervalTrigger(minutes=interval_minutes),
                id=job_id,
                name=f"Sync source: {source.name}",
                replace_existing=True,
                kwargs={"source_id": source.id},
                next_run_time=next_run_time,
            )
            logger.info(
                "Scheduler: added job %s (%s) interval=%d min next=%s",
                job_id,
                source.name,
                interval_minutes,
                next_run_time,
            )

    logger.info("Scheduler: source rescan complete — %d active jobs", len(sources))


def _normalize_source_interval(value: int | None) -> int:
    """Keep source sync interval inside the product-supported lower bound."""
    return max(int(value or 60), 5)


def _next_source_run_time(last_sync_at: datetime | None, interval_minutes: int) -> datetime:
    """Compute the next APScheduler run time from source sync metadata."""
    scheduler_now = datetime.now(scheduler.timezone)
    if last_sync_at is None:
        return scheduler_now + timedelta(seconds=10)

    if last_sync_at.tzinfo is None:
        last_sync_utc = last_sync_at.replace(tzinfo=UTC)
    else:
        last_sync_utc = last_sync_at.astimezone(UTC)

    due_utc = last_sync_utc + timedelta(minutes=interval_minutes)
    if due_utc <= datetime.now(UTC):
        return scheduler_now + timedelta(seconds=10)
    return due_utc.astimezone(scheduler.timezone)


def _source_job_is_overdue(job, expected_next_run_time: datetime) -> bool:
    """Return true when a registered job is later than the source-derived due time."""
    if job.next_run_time is None:
        return True
    return job.next_run_time > expected_next_run_time + timedelta(seconds=30)


@track_job("save_trending_snapshots", name="趋势快照保存", timeout=120, description="每日00:30保存趋势数据快照")
async def _save_trending_snapshots() -> None:
    """Save daily snapshot for all trending sources at 00:30."""
    logger.info("Scheduler: save_trending_snapshots started")
    try:
        async with async_session() as db:
            from app.services.trending_snapshot import save_all_snapshots

            results = await save_all_snapshots(db)
            await db.commit()
        logger.info("Scheduler: trending snapshots saved — %s", results)
        return str(results)
    except Exception:
        logger.exception("Scheduler: save_trending_snapshots failed")


@track_job(
    "cleanup_trending_snapshots", name="清理过期趋势快照", timeout=60, description="每日01:00清理15天前的趋势快照"
)
async def _cleanup_old_trending_snapshots() -> None:
    """Delete trending snapshots older than 15 days at 01:00."""
    logger.info("Scheduler: cleanup_old_trending_snapshots started")
    try:
        async with async_session() as db:
            from app.services.trending_snapshot import cleanup_old_snapshots

            count = await cleanup_old_snapshots(db)
            await db.commit()
        logger.info("Scheduler: cleanup_old_trending_snapshots removed %d records", count)
        return f"removed={count}"
    except Exception:
        logger.exception("Scheduler: cleanup_old_trending_snapshots failed")


@track_job("sync_fanqie", name="番茄小说榜单抓取", timeout=300, description="每日凌晨1点抓取番茄小说34个分类榜单")
async def _sync_fanqie() -> None:
    """番茄小说榜单每日抓取（凌晨1点）。任务永远注册，运行时由 flag 决定是否执行。"""
    async with async_session() as db:
        from app.models.app_setting import get_feature_flag_async
        if not await get_feature_flag_async(db, "webnovel_module"):
            return  # 网文模块未启用，跳过抓取
    logger.info("Scheduler: fanqie sync started")
    try:
        from app.services.fanqie_service import full_sync

        result = await full_sync()
        logger.info("Scheduler: fanqie sync done — %s", result)
        return str(result)
    except Exception:
        logger.exception("Scheduler: fanqie sync failed")


@track_job("sync_qimao", name="七猫小说榜单抓取", timeout=300, description="每日凌晨2点抓取七猫小说10个榜单")
async def _sync_qimao() -> None:
    """七猫小说榜单每日抓取（凌晨2点）。任务永远注册，运行时由 flag 决定是否执行。"""
    async with async_session() as db:
        from app.models.app_setting import get_feature_flag_async
        if not await get_feature_flag_async(db, "webnovel_module"):
            return
    logger.info("Scheduler: qimao sync started")
    try:
        from app.services.qimao_service import sync_qimao_ranks

        result = await sync_qimao_ranks()
        logger.info("Scheduler: qimao sync done — %s", result)
        return str(result)
    except Exception:
        logger.exception("Scheduler: qimao sync failed")


@track_job("sync_zhihu", name="知乎故事榜单抓取", timeout=300, description="每日凌晨4点抓取知乎故事分类榜单")
async def _sync_zhihu() -> None:
    """知乎故事榜单每日抓取（凌晨4点）。任务永远注册，运行时由 flag 决定是否执行。"""
    async with async_session() as db:
        from app.models.app_setting import get_feature_flag_async
        if not await get_feature_flag_async(db, "webnovel_module"):
            return
    logger.info("Scheduler: zhihu sync started")
    try:
        from app.services.zhihu_service import sync_zhihu_ranks

        result = await sync_zhihu_ranks()
        logger.info("Scheduler: zhihu sync done — %s", result)
        return str(result)
    except Exception:
        logger.exception("Scheduler: zhihu sync failed")


# ── NEW: AI 日报 & 周刊定时任务 ──────────────────────────────────────


@track_job("daily_report", name="AI日报生成", timeout=300, description="按时间窗口生成日报快照/最终版，基于精选内容")
async def _generate_daily_report() -> None:
    """Generate current-day daily report snapshot."""
    logger.info("Scheduler: daily report generation started")
    try:
        from app.services.daily_report import generate_daily_report

        async with async_session() as db:
            report = await generate_daily_report(db)
        logger.info("Scheduler: daily report generated — %s (%s)", report.report_date, report.status)
        return f"date={report.report_date}, status={report.status}"
    except Exception:
        logger.exception("Scheduler: daily report generation failed")


@track_job("daily_report_final", name="AI日报完整复盘", timeout=300, description="每日凌晨生成前一天完整日报")
async def _generate_daily_report_final() -> None:
    """Generate previous day's full final daily report."""
    logger.info("Scheduler: daily final report generation started")
    try:
        from app.services.daily_report import generate_previous_day_final_report

        async with async_session() as db:
            report = await generate_previous_day_final_report(db)
        logger.info("Scheduler: daily final report generated — %s (%s)", report.report_date, report.status)
        return f"date={report.report_date}, edition={report.edition}, status={report.status}"
    except Exception:
        logger.exception("Scheduler: daily final report generation failed")


@track_job("weekly_digest", name="AI周刊生成", timeout=300, description="每周一早9点生成AI周刊，基于本周已分析内容")
# ── User-owned daily reports (T2) ────────────────────────────────────────
# Generates a per-user daily report for Pro+ users that have enabled
# private sources. Uses the same edition as the global daily report but
# scoped to owner_user_id. Runs 10 minutes after the global report to
# avoid stampede on the LLM gateway.


async def _list_pro_users_with_private_sources() -> list[int]:
    """Return user ids that (a) are Pro/Studio/Enterprise and (b) have at
    least one enabled private source."""
    from sqlalchemy import and_, exists, select

    from app.core.database import async_session
    from app.models.source import Source
    from app.models.user import User

    async with async_session() as db:
        stmt = (
            select(User.id)
            .where(User.is_active.is_(True))
            .where(User.plan.in_(["pro", "studio", "enterprise"]))
            .where(
                exists().where(
                    and_(
                        Source.owner_user_id == User.id,
                        Source.enabled.is_(True),
                    )
                )
            )
        )
        result = await db.execute(stmt)
        return [row[0] for row in result.all()]


@track_job("daily_report_user", name="用户日报生成", timeout=1800)
async def _generate_user_daily_reports() -> None:
    """Generate user-owned daily reports for all Pro+ users with private sources.

    Concurrency strategy: ``asyncio.gather`` of per-user tasks in chunks
    of 5, with a 2-second sleep between chunks to avoid stampeding the
    LLM gateway. Each user is isolated in its own try/except so one
    failure does not block the rest.
    """
    from datetime import date as _date_cls

    from app.core.database import async_session
    from app.services.daily_report import (
        _day_window,
        _edition_for_now,
        generate_daily_report,
    )

    user_ids = await _list_pro_users_with_private_sources()
    if not user_ids:
        logger.info("daily_report_user: no eligible users, skipping")
        return

    edition = _edition_for_now()
    today = _date_cls.today()
    # Use same window as the global daily report
    window_start, window_end = _day_window(today, None, edition)

    succeeded = 0
    failed = 0
    chunk_size = 5
    for i in range(0, len(user_ids), chunk_size):
        chunk = user_ids[i : i + chunk_size]

        async def _gen_for_one(uid: int) -> None:
            async with async_session() as session:
                try:
                    await generate_daily_report(
                        session,
                        target_date=today,
                        edition=edition,
                        owner_user_id=uid,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("daily_report_user: user=%s failed: %s", uid, exc)
                    raise

        results = await asyncio.gather(
            *[_gen_for_one(uid) for uid in chunk],
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, Exception):
                failed += 1
            else:
                succeeded += 1
        if i + chunk_size < len(user_ids):
            await asyncio.sleep(2)

    logger.info(
        "daily_report_user: succeeded=%s failed=%s (edition=%s window=%s..%s)",
        succeeded,
        failed,
        edition,
        window_start,
        window_end,
    )


async def _generate_weekly_digest() -> None:
    """Generate AI weekly digest at 09:00 every Monday."""
    logger.info("Scheduler: weekly digest generation started")
    try:
        from app.services.weekly_digest import generate_weekly_digest

        async with async_session() as db:
            digest = await generate_weekly_digest(db)
        logger.info("Scheduler: weekly digest generated — %s (%s)", digest.week_key, digest.status)
        return f"week={digest.week_key}, status={digest.status}"
    except Exception:
        logger.exception("Scheduler: weekly digest generation failed")


# ── Lifecycle helpers ─────────────────────────────────────────────────


def start_scheduler() -> None:
    """Register all scheduled jobs and start the scheduler."""
    if scheduler.running:
        logger.info("Scheduler already running; start skipped")
        return

    # Periodic rescan to catch new/updated/disabled sources
    scheduler.add_job(
        _rescan_sources,
        trigger=IntervalTrigger(minutes=10),
        id="rescan_sources",
        name="Rescan enabled sources and update scheduler",
        replace_existing=True,
    )

    # Daily cleanup at 03:00
    scheduler.add_job(
        cleanup_old_content,
        trigger=CronTrigger(hour=3, minute=0),
        id="cleanup_old_content",
        name="Cleanup old pending content",
        replace_existing=True,
    )

    # Notifications cleanup at 03:30 (错开 03:00 避免和 content cleanup 抢 SQLite 写锁)
    scheduler.add_job(
        cleanup_old_notifications,
        trigger=CronTrigger(hour=3, minute=30),
        id="cleanup_old_notifications",
        name="Cleanup old notifications",
        replace_existing=True,
    )

    # Trending radar: sync all trending sources every 30 minutes
    scheduler.add_job(
        _sync_all_trending,
        trigger=IntervalTrigger(minutes=30),
        id="sync_trending",
        name="Sync all trending sources",
        replace_existing=True,
    )

    # Shared post-sync processing is intentionally throttled and decoupled from
    # per-source jobs to keep source fetch intervals reliable on SQLite.
    scheduler.add_job(
        _run_post_sync_pipeline,
        trigger=IntervalTrigger(minutes=5),
        id="post_sync_pipeline",
        name="Process pending analysis after source sync",
        replace_existing=True,
    )

    # Trending snapshot: save daily snapshot at 00:30
    scheduler.add_job(
        _save_trending_snapshots,
        trigger=CronTrigger(hour=0, minute=30),
        id="save_trending_snapshots",
        name="Save daily trending snapshots",
        replace_existing=True,
    )

    # Cleanup trending snapshots at 01:00
    scheduler.add_job(
        _cleanup_old_trending_snapshots,
        trigger=CronTrigger(hour=1, minute=0),
        id="cleanup_trending_snapshots",
        name="Cleanup trending snapshots older than 15 days",
        replace_existing=True,
    )

    # 番茄小说榜单：每日凌晨1点抓取（任务永远注册，运行时由 _sync_fanqie 内 flag 检查决定是否执行）
    scheduler.add_job(
        _sync_fanqie,
        trigger=CronTrigger(hour=1, minute=0),
        id="sync_fanqie",
        name="番茄小说榜单每日抓取",
        replace_existing=True,
    )

    # AI日报：午间、晚间生成当日快照
    scheduler.add_job(
        _generate_daily_report,
        trigger=CronTrigger(hour=12, minute=0),
        id="daily_report_noon",
        name="AI日报午间快照",
        replace_existing=True,
    )
    scheduler.add_job(
        _generate_daily_report,
        trigger=CronTrigger(hour=20, minute=0),
        id="daily_report_evening",
        name="AI日报晚间快照",
        replace_existing=True,
    )
    # 用户专属日报：错开全局 10 分钟，避免 LLM gateway 拥堵
    scheduler.add_job(
        _generate_user_daily_reports,
        trigger=CronTrigger(hour=12, minute=10),
        id="daily_report_user_noon",
        name="用户日报午间",
        replace_existing=True,
    )
    scheduler.add_job(
        _generate_user_daily_reports,
        trigger=CronTrigger(hour=20, minute=10),
        id="daily_report_user_evening",
        name="用户日报晚间",
        replace_existing=True,
    )
    scheduler.add_job(
        _generate_daily_report_final,
        trigger=CronTrigger(hour=0, minute=30),
        id="daily_report_final",
        name="AI日报完整复盘",
        replace_existing=True,
    )

    # AI周刊：每周一凌晨3点生成（总结上周）
    scheduler.add_job(
        _generate_weekly_digest,
        trigger=CronTrigger(day_of_week="mon", hour=3, minute=0),
        id="weekly_digest",
        name="AI周刊生成",
        replace_existing=True,
    )

    # 七猫小说榜单：每日凌晨2点抓取（任务永远注册，运行时由 _sync_qimao 内 flag 检查决定是否执行）
    scheduler.add_job(
        _sync_qimao,
        trigger=CronTrigger(hour=2, minute=0),
        id="sync_qimao",
        name="七猫小说榜单每日抓取",
        replace_existing=True,
    )

    # 知乎故事榜单：每日凌晨4点抓取
    scheduler.add_job(
        _sync_zhihu,
        trigger=CronTrigger(hour=4, minute=0),
        id="sync_zhihu",
        name="知乎故事榜单每日抓取",
        replace_existing=True,
    )

    scheduler.start()

    # Immediately register all enabled sources so they start syncing
    # right away instead of waiting for the first 10-minute rescan.
    import asyncio as _asyncio

    try:
        loop = _asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(_rescan_sources())
            logger.info("Scheduler: initial source rescan scheduled immediately")
    except RuntimeError:
        logger.warning("Scheduler: could not schedule initial rescan (no event loop)")

    logger.info(
        "Scheduler started: per-source sync + 10min rescan + 5min post-sync + cleanup + "
        "daily_report(12:00/20:00 + final 00:30) + weekly_digest(Mon 09:00)"
    )


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler.

    wait=True lets in-flight jobs finish (up to APScheduler's internal
    timeout), so SIGTERM during a source sync doesn't kill the task
    mid-write (which is what left sources stuck in SYNCING status).
    """
    if scheduler.running:
        try:
            scheduler.shutdown(wait=True)
            logger.info("Scheduler shut down gracefully (in-flight jobs completed)")
        except Exception as exc:
            # If wait=True hangs (e.g. a job stuck on a long network call),
            # force shutdown so the container can still exit.
            logger.warning("Graceful scheduler shutdown failed (%s), forcing", exc)
            scheduler.shutdown(wait=False)
            logger.info("Scheduler forced shutdown")
