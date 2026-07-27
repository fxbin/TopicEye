from __future__ import annotations

from app.services.json_cache import invalidate_json_cache

STATS_CACHE_PREFIX = "stats:"
STATS_DASHBOARD_CACHE_PREFIX = "stats:dashboard:"
STATS_NOVEL_PLATFORMS_CACHE_KEY = "stats:novel-platforms"


def invalidate_stats_cache() -> None:
    invalidate_json_cache(STATS_CACHE_PREFIX)


def invalidate_novel_platform_stats_cache() -> None:
    invalidate_json_cache(STATS_NOVEL_PLATFORMS_CACHE_KEY)
    invalidate_json_cache(STATS_DASHBOARD_CACHE_PREFIX)
