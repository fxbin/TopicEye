"""
趋势雷达 pipeline。

每次同步：
1. 抓取新数据（batch_id = source + timestamp）
2. 删除该 source 的旧数据
3. 批量插入新数据
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Union

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trending import TrendingItem
from app.services.trending_cache import invalidate_trending_cache
from app.services.trending_scrapers import get_trending_cls, get_all_trending_sources
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)


async def sync_trending_source(source_name: str, db: AsyncSession) -> Dict[str, Union[int, str]]:
    """同步单个趋势源。返回 {"fetched": N}"""
    scraper_cls = get_trending_cls(source_name)
    if scraper_cls is None:
        logger.warning("No trending scraper for '%s'", source_name)
        return {"fetched": 0}

    scraper = scraper_cls()
    batch_id = f"{source_name}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

    try:
        proxy_url = os.environ.get("https_proxy") or os.environ.get("HTTPS_PROXY")
        client_kwargs = {"timeout": 30, "follow_redirects": True}
        if proxy_url:
            client_kwargs["proxy"] = proxy_url

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
                fetched_at=datetime.now(timezone.utc),
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


async def sync_all_trending(db: AsyncSession) -> Dict[str, Dict[str, int]]:
    """同步所有趋势源。

    SQLite has a single writer lock. Commit after each source so network fetches
    and the next source do not keep earlier writes open and block lightweight
    user actions such as favoriting content.
    """
    results = {}
    for source_name in get_all_trending_sources():
        result = await sync_trending_source(source_name, db)
        await db.commit()
        results[source_name] = result
    return results
