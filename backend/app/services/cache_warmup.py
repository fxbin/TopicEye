from __future__ import annotations

import logging
import time
from datetime import UTC
from typing import Any

from app.core.database import async_session
from app.repositories.content_repo import ContentRepo
from app.repositories.source_repo import SourceRepository
from app.schemas.source import SourceListResponse
from app.services.content_list_cache import (
    HOME_CONTENT_LIST_CACHE_LABEL,
    home_content_list_cache_params,
    set_cached_content_list,
)
from app.services.content_serialization import content_with_latest_analysis
from app.services.json_cache import set_cached_json
from app.services.source_cache import (
    SOURCE_LIST_DEFAULT_CACHE_LABEL,
    default_source_list_cache_params,
    set_cached_source_list,
)
from app.services.today_picks_cache import (
    TODAY_PICKS_DEFAULT_CACHE_LABEL,
    default_today_picks_cache_params,
    set_cached_today_picks,
)

logger = logging.getLogger(__name__)


async def warmup_startup_critical_caches() -> dict[str, Any]:
    """Warm read caches needed by first-screen creator workflows."""
    started_at = time.perf_counter()
    warmed: list[str] = []
    errors: list[str] = []

    async with async_session() as db:
        try:
            warmed.extend(await warmup_scoring_flow(db))
        except Exception as exc:
            logger.warning("Startup scoring flow cache warmup skipped: %s", exc)
            errors.append(f"scoring-flow:{exc}")

    try:
        warmed.extend(await warmup_stats_workspace())
    except Exception as exc:
        logger.warning("Startup stats workspace cache warmup skipped: %s", exc)
        errors.append(f"stats:{exc}")

    # 趋势雷达页面预热:用户进入后首个请求即可命中缓存,
    # 避免冷启动 3s 等待(尤其 /persistent 的 Python 嵌套循环)
    async with async_session() as db:
        try:
            warmed.extend(await warmup_trending_workspace(db))
        except Exception as exc:
            logger.warning("Startup trending workspace cache warmup skipped: %s", exc)
            errors.append(f"trending:{exc}")

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info("Startup critical cache warmup completed in %.1fms: %s", elapsed_ms, ", ".join(warmed) or "none")
    return {"warmed": warmed, "errors": errors, "elapsed_ms": elapsed_ms}


async def warmup_read_caches(*, include_scoring_flow: bool = True, include_stats: bool = True) -> dict[str, Any]:
    """Warm hot read caches without blocking application startup."""
    started_at = time.perf_counter()
    warmed: list[str] = []
    errors: list[str] = []

    async with async_session() as db:
        try:
            await warmup_sources_list(db)
            warmed.append(SOURCE_LIST_DEFAULT_CACHE_LABEL)
        except Exception as exc:
            logger.warning("Source list cache warmup skipped: %s", exc)
            errors.append(f"sources:{exc}")

        try:
            await warmup_content_list(db)
            warmed.append(HOME_CONTENT_LIST_CACHE_LABEL)
        except Exception as exc:
            logger.warning("Content list cache warmup skipped: %s", exc)
            errors.append(f"contents:{exc}")

        try:
            await warmup_today_picks(db)
            warmed.append(TODAY_PICKS_DEFAULT_CACHE_LABEL)
        except Exception as exc:
            logger.warning("Today picks cache warmup skipped: %s", exc)
            errors.append(f"today-picks:{exc}")

        try:
            await warmup_content_favorites(db)
            warmed.append("contents:favorites:list:1:20")
        except Exception as exc:
            logger.warning("Content favorites cache warmup skipped: %s", exc)
            errors.append(f"favorites:{exc}")

        if include_stats:
            try:
                warmed.extend(await warmup_stats_workspace())
            except Exception as exc:
                logger.warning("Stats workspace cache warmup skipped: %s", exc)
                errors.append(f"stats:{exc}")

        try:
            warmed.extend(await warmup_trending_workspace(db))
        except Exception as exc:
            logger.warning("Trending workspace cache warmup skipped: %s", exc)
            errors.append(f"trending:{exc}")

        if include_scoring_flow:
            try:
                warmed.extend(await warmup_scoring_flow(db))
            except Exception as exc:
                logger.warning("Scoring flow cache warmup skipped: %s", exc)
                errors.append(f"scoring-flow:{exc}")

    elapsed_ms = (time.perf_counter() - started_at) * 1000
    logger.info("Read cache warmup completed in %.1fms: %s", elapsed_ms, ", ".join(warmed) or "none")
    return {"warmed": warmed, "errors": errors, "elapsed_ms": elapsed_ms}


async def warmup_sources_list(db) -> None:
    params = default_source_list_cache_params()
    repo = SourceRepository(db)
    items, total = await repo.list_paginated(
        page=params.page,
        page_size=params.page_size,
        filters={},
        sort_by="sort_order",
        sort_order="asc",
    )
    payload = SourceListResponse(items=items, total=total, page=params.page, page_size=params.page_size).model_dump()
    set_cached_source_list(params, payload)


async def warmup_content_favorites(db) -> None:
    items, total = await ContentRepo(db).list_favorites(page=1, page_size=20)
    payload = {
        "items": [content_with_latest_analysis(item) for item in items],
        "total": total,
        "page": 1,
        "page_size": 20,
    }
    set_cached_json("contents:favorites:list:1:20", payload)


async def warmup_content_list(db) -> None:
    from datetime import datetime, timedelta

    from app.repositories.ignored_repo import IgnoredRepo

    params = home_content_list_cache_params()
    ignored_ids = await IgnoredRepo(db).list_ignored_ids()
    items, total = await ContentRepo(db).list_paginated_with_analyses(
        page=params.page,
        page_size=params.page_size,
        filters=None,
        sort_by=params.sort_by,
        sort_order=params.sort_order,
        exclude_ids=ignored_ids,
        exclude_source_types={"DouyinHot"},
        time_cutoff=datetime.now(UTC) - timedelta(hours=params.hours or 48),
    )
    payload = {
        "items": [content_with_latest_analysis(item) for item in items],
        "total": total,
        "page": params.page,
        "page_size": params.page_size,
    }
    set_cached_content_list(params, payload)


async def warmup_today_picks(db) -> None:
    from app.services.today_picks import build_today_picks

    params = default_today_picks_cache_params()
    payload = await build_today_picks(db, hours=params.hours, limit=params.limit)
    set_cached_today_picks(params, payload)


async def warmup_stats_workspace() -> list[str]:
    from app.services.stats_workspace import build_default_stats_cache_payloads

    payloads = build_default_stats_cache_payloads()
    for key, payload in payloads.items():
        set_cached_json(key, payload)
    return list(payloads)


async def warmup_trending_workspace(db) -> list[str]:
    from app.api.v1.trending import build_default_trending_cache_payloads

    payloads = await build_default_trending_cache_payloads(db)
    for key, payload in payloads.items():
        set_cached_json(key, payload)
    return list(payloads)


async def warmup_scoring_flow(db) -> list[str]:
    from app.services.scoring_flow import SCORING_FLOW_WARMUP_TARGETS, build_scoring_flow_payload

    warmed: list[str] = []
    for hours, limit in SCORING_FLOW_WARMUP_TARGETS:
        await build_scoring_flow_payload(db, hours=hours, limit=limit)
        warmed.append(f"scoring-flow:{hours}:{limit}")
    return warmed
