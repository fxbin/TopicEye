"""
趋势雷达 pipeline。

每次同步：
1. 抓取新数据（batch_id = source + timestamp）
2. 删除该 source 的旧数据
3. 批量插入新数据
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

import httpx
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import async_session
from app.models.trending import TrendingItem
from app.services.scraper_http import build_browser_client_kwargs
from app.services.trending_cache import invalidate_trending_cache
from app.services.trending_scrapers import (
    get_syncable_trending_sources,
    get_trending_cls,
)
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)

# Per-source 锁：防止手动单刷 (/sync/{source}) 和定时全量 (sync_all_trending)
# 对同一 source 并发 delete-then-insert 导致丢数据。不同 source 不互斥，
# 不影响 sync_all_trending 的并发度。仿 job_tracker._job_locks 模式。
_source_locks: dict[str, asyncio.Lock] = {}


def _get_source_lock(source_name: str) -> asyncio.Lock:
    lock = _source_locks.get(source_name)
    if lock is None:
        lock = asyncio.Lock()
        _source_locks[source_name] = lock
    return lock


async def sync_trending_source(source_name: str, db: AsyncSession) -> dict[str, int | str]:
    """同步单个趋势源。返回 {"fetched": N}

    整个抓取+入库过程持有 per-source 锁，避免手动单刷与定时全量对同一
    source 并发 delete-then-insert 导致数据丢失。
    """
    async with _get_source_lock(source_name):
        return await _sync_trending_source_locked(source_name, db)


async def _sync_trending_source_locked(source_name: str, db: AsyncSession) -> dict[str, int | str]:
    scraper_cls = get_trending_cls(source_name)
    if scraper_cls is None:
        logger.warning("No trending scraper for '%s'", source_name)
        return {"fetched": 0}

    scraper = scraper_cls()
    batch_id = f"{source_name}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}"

    try:
        client_kwargs = build_browser_client_kwargs()

        async with httpx.AsyncClient(**client_kwargs) as client:
            entries = await scraper.fetch(client)

        if not entries:
            logger.info("trending %s: no entries fetched", source_name)
            return {"fetched": 0}

        # 删除该 source 的旧数据
        await db.execute(delete(TrendingItem).where(TrendingItem.source == source_name))

        # 批量插入
        for entry in entries:
            item = TrendingItem(
                source=source_name,
                category=scraper.CATEGORY,
                rank=entry.get("rank", 0),
                title=entry.get("title", ""),
                url=normalize_zhihu_url(entry.get("url", "")),
                hot_value=entry.get("hot_value", 0),
                hot_value_raw=entry.get("hot_value_raw", ""),
                trend=entry.get("trend"),
                cover_url=entry.get("cover_url"),
                extra=entry.get("extra"),
                fetched_at=datetime.now(UTC),
                batch_id=batch_id,
            )
            db.add(item)

        await db.flush()
        invalidate_trending_cache()
        logger.info("trending %s: synced %d items (batch %s)", source_name, len(entries), batch_id)
        return {"fetched": len(entries)}

    except Exception as exc:
        logger.exception("Error syncing trending source '%s'", source_name)
        await db.rollback()
        return {"fetched": 0, "error": str(exc)[:200]}


async def sync_all_trending(db: AsyncSession) -> dict[str, dict[str, int]]:
    """并发同步所有趋势源。

    每个源开独立 session（AsyncSession 不可并发共享），gather 保证单源
    失败/超时不影响其他源。瓶颈在网络 I/O 而非 DB 写：串行模式下 8 个
    国内信源 ConnectError 各卡 ~3s 累加 20s+，会把整个任务拖过 120s job
    超时；并发后这些同时失败，总耗时≈最慢单源。

    db 参数保留以兼容现有调用点（scheduler.py / api），但并发抓取不再
    复用它——每个源各自 async with async_session()。db 仍由调用方关闭。
    """
    sources = get_syncable_trending_sources()
    concurrency = _normalize_trending_concurrency()
    semaphore = asyncio.Semaphore(concurrency)

    async def sync_one(name: str) -> dict[str, int | str]:
        async with semaphore, async_session() as src_db:
            try:
                result = await sync_trending_source(name, src_db)
                await src_db.commit()
                return result
            except Exception:
                await src_db.rollback()
                raise

    raw_results = await asyncio.gather(*(sync_one(name) for name in sources), return_exceptions=True)

    results: dict[str, dict[str, int | str]] = {}
    for name, item in zip(sources, raw_results, strict=False):
        if isinstance(item, BaseException):
            logger.exception("Unexpected error syncing trending source '%s'", name, exc_info=item)
            results[name] = {"fetched": 0, "error": f"{type(item).__name__}: {item}"}
        else:
            results[name] = item
    return results


def _normalize_trending_concurrency() -> int:
    """读取并发度配置，clamp 到 [1, 20]。"""
    try:
        parsed = int(settings.TRENDING_SYNC_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 8
    return max(1, min(parsed, 20))
