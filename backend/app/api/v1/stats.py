"""Dashboard statistics API endpoints backed by DuckDB analytics."""

from __future__ import annotations

import logging
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.config import settings  # noqa: F401 — accessed via stats.settings in tests
from app.core.database import async_session
from app.services.duckdb_service import (
    query_dashboard_stats,
    query_stats_category_distribution,
    query_stats_daily_trend,
    query_stats_novel_platforms,
    query_stats_overview,
    query_stats_source_distribution,
    run_query,
)
from app.services.json_cache import get_cached_json, set_cached_json

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/stats", tags=["stats"], dependencies=[Depends(get_current_user)])
ANALYTICS_HEADERS = {"X-Analytics-Backend": "duckdb"}
DEFAULT_STATS_DAYS = 30
STATS_CACHE_KEYS = {
    "overview": "stats:overview:{days}",
    "source_distribution": "stats:source-distribution:{days}",
    "category_distribution": "stats:category-distribution:{days}",
    "daily_trend": "stats:daily-trend:{days}",
    "novel_platforms": "stats:novel-platforms",
    "dashboard": "stats:dashboard:{days}",
}


def _stats_cache_key(name: str, *, days: int | None = None) -> str:
    template = STATS_CACHE_KEYS[name]
    return template.format(days=days) if days is not None else template


def _cached_response(cache_key: str) -> Response | None:
    # stats 是聚合统计，用更长的 TTL（5 分钟），不随单条内容增删失效。
    # 采集/分析不再触发 invalidate_stats_cache，靠 TTL 自然过期 + 定时任务后显式刷新。
    cached = get_cached_json(cache_key, ttl_seconds=300.0)
    if not cached:
        return None
    content, age_seconds = cached
    return Response(
        content=content,
        media_type="application/json",
        headers={
            **ANALYTICS_HEADERS,
            "X-Stats-Cache": "HIT",
            "X-Stats-Cache-Age-Ms": str(round(age_seconds * 1000, 3)),
        },
    )


def _cache_response(cache_key: str, payload: dict) -> Response:
    content = set_cached_json(cache_key, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={**ANALYTICS_HEADERS, "X-Stats-Cache": "MISS"},
    )


def _raise_duckdb_unavailable(exc: Exception) -> None:
    logger.exception("DuckDB stats query failed")
    raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc


async def _query_response(cache_key: str, query: Callable[[], dict]) -> Response:
    try:
        payload = await run_query(query)
    except Exception as exc:
        _raise_duckdb_unavailable(exc)
    return _cache_response(cache_key, payload)


@router.get("/overview")
async def get_overview(days: int = Query(7, ge=1, le=90)):
    """
    内容总览 KPI:
    - total: 总内容数
    - analyzed: 已分析数
    - curated: 精选数
    - today_new: 今日新增
    """
    cache_key = _stats_cache_key("overview", days=days)
    cached = _cached_response(cache_key)
    if cached:
        return cached

    async with async_session() as db:
        try:
            payload = await build_overview_payload(db, days=days)
        except Exception as exc:
            _raise_duckdb_unavailable(exc)
        return _cache_response(cache_key, payload)


async def build_overview_payload(db: AsyncSession, *, days: int) -> dict:
    """Build overview payload through DuckDB; db is accepted for cache warmup compatibility."""
    _ = db
    return await run_query(lambda: query_stats_overview(days=days))


@router.get("/source-distribution")
async def get_source_distribution(days: int = Query(7, ge=1, le=90)):
    """信源分布：source_name, source_type, content_count, curated_count, curation_rate."""
    cache_key = _stats_cache_key("source_distribution", days=days)
    cached = _cached_response(cache_key)
    if cached:
        return cached
    return await _query_response(cache_key, lambda: query_stats_source_distribution(days=days))


@router.get("/category-distribution")
async def get_category_distribution(days: int = Query(7, ge=1, le=90)):
    """分类分布：category, content_count, avg_curation_score."""
    cache_key = _stats_cache_key("category_distribution", days=days)
    cached = _cached_response(cache_key)
    if cached:
        return cached
    return await _query_response(cache_key, lambda: query_stats_category_distribution(days=days))


@router.get("/daily-trend")
async def get_daily_trend(days: int = Query(7, ge=1, le=90)):
    """时间趋势：date, content_count, curated_count, analyzed_count."""
    cache_key = _stats_cache_key("daily_trend", days=days)
    cached = _cached_response(cache_key)
    if cached:
        return cached
    return await _query_response(cache_key, lambda: query_stats_daily_trend(days=days))


@router.get("/novel-platforms")
async def get_novel_platform_stats():
    """网文雷达统计：番茄 / 七猫 / 知乎数量与最近同步时间。"""
    cache_key = _stats_cache_key("novel_platforms")
    cached = _cached_response(cache_key)
    if cached:
        return cached
    return await _query_response(cache_key, query_stats_novel_platforms)


@router.get("/dashboard")
async def get_dashboard_stats(days: int = Query(30, ge=1, le=90)):
    """Legacy dashboard stats: KPI cards + source breakdown + daily volume trend."""
    cache_key = _stats_cache_key("dashboard", days=days)
    cached = _cached_response(cache_key)
    if cached:
        return cached
    return await _query_response(cache_key, lambda: query_dashboard_stats(days=days))
