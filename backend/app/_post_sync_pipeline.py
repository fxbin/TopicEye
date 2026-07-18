"""Post-sync pipeline subsystem.

从 app.scheduler 抽出的信源同步后处理子系统，包括:
- _request_post_sync_pipeline       触发 post-sync 处理
- _clear_post_sync_task             清理 task 引用 + 错误日志
- _run_post_sync_pipeline            周期性 job:分析待处理、聚类、趋势快照
- _run_post_sync_pipeline_once       一次性的分析→聚类→快照
- _drain_pending_analysis            拉取 pending 内容并并发分析
- _release_inflight_analysis_claims  释放超时/失败的 analyzing 声明

外部依赖（保持不变）:
- 共享调度装饰器 track_job、锁、semaphore、positive_int 等仍由 app.scheduler 提供
- 通过模块顶部 import 获取，避免循环依赖
"""

from __future__ import annotations

import asyncio
import logging

import app.scheduler  # noqa: F401 — imported for runtime name lookup (monkeypatch friendly)
from app.core.config import settings
from app.repositories.content_repo import ContentRepo
from app.services.job_tracker import track_job

# async_session 与 analyze_batch_concurrent 在运行时通过 app.scheduler 查找，
# 这样测试通过 monkeypatch.setattr(scheduler_module, "async_session", ...) 和
# monkeypatch.setattr(scheduler_module, "analyze_batch_concurrent", ...) 仍能影响
# 本模块（无需重新 patch 本模块）。

logger = logging.getLogger(__name__)

# Module-local state: only post-sync subsystem touches these.
_post_sync_lock: asyncio.Lock | None = None
_post_sync_task: asyncio.Task | None = None
_post_sync_rerun_requested = False


def _get_post_sync_lock() -> asyncio.Lock:
    global _post_sync_lock
    if _post_sync_lock is None:
        _post_sync_lock = asyncio.Lock()
    return _post_sync_lock


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(value if value is not None else default)
    except (TypeError, ValueError):
        parsed = default
    return max(1, parsed)


def _post_sync_analysis_batch_size() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_ANALYSIS_BATCH_SIZE", 10), 10)


def _post_sync_analysis_time_budget_seconds() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_ANALYSIS_TIME_BUDGET_SECONDS", 520), 520)


def _post_sync_min_remaining_seconds() -> int:
    return _positive_int(getattr(settings, "POST_SYNC_MIN_REMAINING_SECONDS", 90), 90)


def _request_post_sync_pipeline(stats: dict | None = None) -> bool:
    """Request shared post-sync work after a source sync produced new content."""
    global _post_sync_task, _post_sync_rerun_requested

    try:
        if not stats or int(stats.get("new", 0) or 0) <= 0:
            return False
    except (TypeError, ValueError):
        return False

    try:
        # Runtime lookup (not module-level) so test monkeypatch on
        # `app.scheduler.asyncio.get_running_loop` keeps working.
        loop = app.scheduler.asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("Scheduler: could not request post-sync pipeline (no running loop)")
        return False

    lock = _get_post_sync_lock()
    if (_post_sync_task is not None and not _post_sync_task.done()) or lock.locked():
        _post_sync_rerun_requested = True
        logger.info(
            "Scheduler: post-sync pipeline already active; coalesced request for %d new items",
            int(stats.get("new", 0) or 0),
        )
        return True

    _post_sync_task = loop.create_task(_run_post_sync_pipeline())
    _post_sync_task.add_done_callback(_clear_post_sync_task)
    logger.info("Scheduler: requested post-sync pipeline for %d new items", int(stats.get("new", 0) or 0))
    return True


def _clear_post_sync_task(task: asyncio.Task) -> None:
    """Clear the ad-hoc post-sync task reference and surface unexpected failures."""
    global _post_sync_task
    if _post_sync_task is task:
        _post_sync_task = None
    if task.cancelled():
        logger.warning("Scheduler: ad-hoc post-sync pipeline task was cancelled")
        return
    try:
        task.result()
    except Exception:
        logger.exception("Scheduler: ad-hoc post-sync pipeline task failed")


@track_job(
    "post_sync_pipeline",
    name="同步后分析聚合",
    timeout=600,
    description="节流处理待分析内容、话题聚类和趋势快照，避免每个信源同步后重复触发",
)
async def _run_post_sync_pipeline() -> None:
    """Run shared post-sync work, coalescing overlapping sync completions."""
    global _post_sync_rerun_requested

    lock = _get_post_sync_lock()
    if lock.locked():
        _post_sync_rerun_requested = True
        logger.info("Scheduler: post-sync pipeline already running; queued one rerun")
        return

    async with lock:
        while True:
            _post_sync_rerun_requested = False
            await _run_post_sync_pipeline_once()
            if not _post_sync_rerun_requested:
                break
            logger.info("Scheduler: running coalesced post-sync pipeline rerun")


async def _run_post_sync_pipeline_once() -> None:
    """Analyze pending, cluster, and snapshot trends once."""
    analysis_stats = await _drain_pending_analysis()
    if analysis_stats["attempted"] == 0:
        logger.info("Scheduler: post-sync pipeline skipped — no pending content")
        return

    if analysis_stats["analyzed"] == 0:
        logger.info("Scheduler: post-sync pipeline analyzed no items — %s", analysis_stats)
        return

    if analysis_stats["remaining"]:
        logger.info(
            "Scheduler: post-sync pipeline deferred clustering while analysis backlog remains — %s",
            analysis_stats,
        )
        return

    try:
        async with app.scheduler.async_session() as db:
            from app.services.topic_clustering import cluster_and_dedup_with_lease

            stats, claimed = await cluster_and_dedup_with_lease(db, trigger_type="scheduler")
        if claimed:
            logger.info("Scheduler: clustering done — %s", stats)
        else:
            logger.info("Scheduler: clustering skipped because another run holds the lease")
    except Exception:
        logger.exception("Scheduler: clustering failed")

    # 批量分析+聚类完成后刷新 stats 缓存（不再在单条内容增删时失效）
    try:
        from app.services.stats_cache import invalidate_stats_cache
        invalidate_stats_cache()
        logger.info("Scheduler: stats cache invalidated after post-sync pipeline")
    except Exception:
        logger.warning("Scheduler: failed to invalidate stats cache", exc_info=True)

    try:
        async with app.scheduler.async_session() as db:
            from app.services.trends import snapshot_daily_trends

            stats = await snapshot_daily_trends(db)
            await db.commit()
        logger.info("Scheduler: trend snapshot done — %s", stats)
    except Exception:
        logger.exception("Scheduler: trend snapshot failed")


async def _drain_pending_analysis(
    *,
    batch_size: int | None = None,
    time_budget_seconds: int | None = None,
) -> dict[str, int | bool | str]:
    """Analyze pending and stale in-flight content until the time budget is nearly spent.

    The scheduler wrapper has a hard timeout. This helper exits before that
    boundary so the job can finish cleanly instead of being cancelled mid-call
    and leaving more items in ``analyzing``.
    """
    started_at = asyncio.get_running_loop().time()
    batch_size = _positive_int(batch_size, _post_sync_analysis_batch_size())
    time_budget_seconds = _positive_int(time_budget_seconds, _post_sync_analysis_time_budget_seconds())
    min_remaining_seconds = _post_sync_min_remaining_seconds()
    attempted = 0
    analyzed = 0
    batches = 0
    stop_reason = "no_pending"

    while True:
        elapsed = asyncio.get_running_loop().time() - started_at
        remaining_seconds = time_budget_seconds - elapsed
        if remaining_seconds < min_remaining_seconds:
            stop_reason = "time_budget"
            break

        async with app.scheduler.async_session() as db:
            content_repo = ContentRepo(db)
            pending_ids = await content_repo.claim_pending_analysis_ids(limit=batch_size)
            await db.commit()

        if not pending_ids:
            stop_reason = "no_pending"
            break

        attempted += len(pending_ids)
        batches += 1
        try:
            # Lookup at call time (not import time) so test monkeypatch on
            # `app.scheduler.analyze_batch_concurrent` keeps working — the function
            # is defined in scheduler.py and re-exported from there.
            import app.scheduler as _scheduler_module
            results = await asyncio.wait_for(
                _scheduler_module.analyze_batch_concurrent(pending_ids, assume_claimed=True),
                timeout=max(1, remaining_seconds - 10),
            )
        except TimeoutError:
            logger.warning("Scheduler: auto-analysis batch timed out for ids=%s", pending_ids)
            released = await _release_inflight_analysis_claims(pending_ids)
            logger.info("Scheduler: released %d timed-out analysis claims", released)
            stop_reason = "batch_timeout"
            break
        except Exception:
            logger.exception("Scheduler: auto-analysis batch failed for ids=%s", pending_ids)
            released = await _release_inflight_analysis_claims(pending_ids)
            logger.info("Scheduler: released %d failed analysis claims", released)
            stop_reason = "batch_failed"
            break

        analyzed += len(results)
        logger.info(
            "Scheduler: auto-analysis batch complete attempted=%d analyzed=%d ids=%s",
            len(pending_ids),
            len(results),
            pending_ids,
        )

        if not results:
            stop_reason = "no_progress"
            break

    async with app.scheduler.async_session() as db:
        content_repo = ContentRepo(db)
        remaining = await content_repo.list_pending_for_analysis(limit=1)

    return {
        "attempted": attempted,
        "analyzed": analyzed,
        "batches": batches,
        "remaining": bool(remaining),
        "stop_reason": stop_reason,
    }


async def _release_inflight_analysis_claims(content_ids: list[int]) -> int:
    """Return still-analyzing items from a cancelled scheduler batch to pending."""
    async with app.scheduler.async_session() as db:
        content_repo = ContentRepo(db)
        released = await content_repo.release_analyzing_to_pending(content_ids)
        await db.commit()
        return released