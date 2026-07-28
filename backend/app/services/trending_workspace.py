"""Service-owned default trending workspace payloads for cache warmup."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.trending_repo import TrendingRepository
from app.services.trending_cache import (
    TRENDING_SOURCES_CACHE_KEY,
    CrossPlatformCacheParams,
    PersistentTopicsCacheParams,
    TrendingListCacheParams,
)
from app.services.trending_cross import cluster_trending_items
from app.services.trending_snapshot import analyze_persistent_topics
from app.services.zhihu_url import normalize_zhihu_url

DEFAULT_TRENDING_LIST_LIMIT = 200
DEFAULT_TRENDING_MIN_RESONANCE = 2
DEFAULT_TRENDING_CROSS_LIMIT = 50
DEFAULT_TRENDING_MIN_DAYS = 2
DEFAULT_TRENDING_MIN_SOURCES = 1
DEFAULT_TRENDING_DAYS_BACK = 7


def _enum_value(value: object) -> str:
    return str(getattr(value, "value", value))


async def build_default_trending_cache_payloads(db: AsyncSession) -> dict[str, object]:
    """Build standard trending warmup payloads without importing API handlers."""
    repo = TrendingRepository(db)
    list_params = TrendingListCacheParams(limit=DEFAULT_TRENDING_LIST_LIMIT)
    cross_params = CrossPlatformCacheParams(
        min_resonance=DEFAULT_TRENDING_MIN_RESONANCE,
        limit=DEFAULT_TRENDING_CROSS_LIMIT,
    )
    persistent_params = PersistentTopicsCacheParams(
        min_days=DEFAULT_TRENDING_MIN_DAYS,
        min_sources=DEFAULT_TRENDING_MIN_SOURCES,
        days_back=DEFAULT_TRENDING_DAYS_BACK,
    )
    items = await repo.list_with_filters(limit=DEFAULT_TRENDING_LIST_LIMIT)
    all_items = await repo.list_all_ordered_by_source_rank()
    grouped = await repo.list_grouped_by_source_category()
    clusters = cluster_trending_items(
        [
            {
                "id": item.id,
                "source": _enum_value(item.source),
                "category": _enum_value(item.category),
                "rank": item.rank,
                "title": item.title,
                "url": normalize_zhihu_url(item.url),
                "hot_value": item.hot_value,
                "hot_value_raw": item.hot_value_raw,
                "trend": item.trend,
                "extra": item.extra,
            }
            for item in all_items
        ]
    )
    clusters = [cluster for cluster in clusters if cluster["resonance"] >= DEFAULT_TRENDING_MIN_RESONANCE][
        :DEFAULT_TRENDING_CROSS_LIMIT
    ]
    for cluster in clusters:
        for item in cluster.get("items", []):
            item.pop("_keywords", None)
    topics = await analyze_persistent_topics(
        db,
        DEFAULT_TRENDING_MIN_DAYS,
        DEFAULT_TRENDING_MIN_SOURCES,
        DEFAULT_TRENDING_DAYS_BACK,
    )
    return {
        list_params.key: [
            {
                "id": item.id,
                "source": _enum_value(item.source),
                "category": _enum_value(item.category),
                "rank": item.rank,
                "title": item.title,
                "url": normalize_zhihu_url(item.url),
                "hot_value": item.hot_value,
                "hot_value_raw": item.hot_value_raw,
                "trend": item.trend,
                "cover_url": item.cover_url,
                "extra": item.extra,
            }
            for item in items
        ],
        TRENDING_SOURCES_CACHE_KEY: [
            {
                "source": _enum_value(source),
                "category": _enum_value(category),
                "count": count,
                "last_synced": last_synced.isoformat() if last_synced else None,
            }
            for source, category, count, last_synced in grouped
        ],
        cross_params.key: {"total": len(clusters), "clusters": clusters},
        persistent_params.key: {"total": len(topics), "topics": topics},
    }
