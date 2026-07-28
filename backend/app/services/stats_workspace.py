"""Service-owned default dashboard-stat payloads for cache warmup."""

from __future__ import annotations

from app.services.duckdb_service import (
    query_dashboard_stats,
    query_stats_category_distribution,
    query_stats_daily_trend,
    query_stats_novel_platforms,
    query_stats_overview,
    query_stats_source_distribution,
)

DEFAULT_STATS_DAYS = 30


def build_default_stats_cache_payloads() -> dict[str, dict]:
    """Build the standard stats workspace payloads without importing API code."""
    days = DEFAULT_STATS_DAYS
    return {
        f"stats:overview:{days}": query_stats_overview(days=days),
        f"stats:source-distribution:{days}": query_stats_source_distribution(days=days),
        f"stats:category-distribution:{days}": query_stats_category_distribution(days=days),
        f"stats:daily-trend:{days}": query_stats_daily_trend(days=days),
        "stats:novel-platforms": query_stats_novel_platforms(),
        f"stats:dashboard:{days}": query_dashboard_stats(days=days),
    }
