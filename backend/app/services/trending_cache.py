"""Read cache helpers for trending radar endpoints."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json

TRENDING_LIST_CACHE_PREFIX = "trending:list:"
TRENDING_SOURCES_CACHE_KEY = "trending:sources"
TRENDING_CROSS_PLATFORM_CACHE_PREFIX = "trending:cross-platform:"
TRENDING_PERSISTENT_CACHE_PREFIX = "trending:persistent:"


@dataclass(frozen=True)
class TrendingListCacheParams:
    category: str | None = None
    source: str | None = None
    limit: int = 30
    exclude_sources: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        params: dict = {"limit": self.limit}
        if self.category:
            params["category"] = self.category
        if self.source:
            params["source"] = self.source
        if self.exclude_sources:
            # Sort for stable cache key regardless of param ordering
            params["exclude_sources"] = ",".join(sorted(self.exclude_sources))
        return TRENDING_LIST_CACHE_PREFIX + urlencode(params)


def get_cached_trending_list(params: TrendingListCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_trending_list(params: TrendingListCacheParams, payload: list) -> bytes:
    return set_cached_json(params.key, payload)


def get_cached_trending_sources(*, ttl_seconds: float):
    return get_cached_json(TRENDING_SOURCES_CACHE_KEY, ttl_seconds=ttl_seconds)


def set_cached_trending_sources(payload: list) -> bytes:
    return set_cached_json(TRENDING_SOURCES_CACHE_KEY, payload)


@dataclass(frozen=True)
class CrossPlatformCacheParams:
    min_resonance: int = 1
    limit: int = 30

    @property
    def key(self) -> str:
        return TRENDING_CROSS_PLATFORM_CACHE_PREFIX + urlencode({
            "min_resonance": self.min_resonance,
            "limit": self.limit,
        })


@dataclass(frozen=True)
class PersistentTopicsCacheParams:
    min_days: int = 2
    min_sources: int = 1
    days_back: int = 7

    @property
    def key(self) -> str:
        return TRENDING_PERSISTENT_CACHE_PREFIX + urlencode({
            "min_days": self.min_days,
            "min_sources": self.min_sources,
            "days_back": self.days_back,
        })


def get_cached_cross_platform(params: CrossPlatformCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_cross_platform(params: CrossPlatformCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def get_cached_persistent_topics(params: PersistentTopicsCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_persistent_topics(params: PersistentTopicsCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def invalidate_trending_cache() -> None:
    invalidate_json_cache(TRENDING_LIST_CACHE_PREFIX)
    invalidate_json_cache(TRENDING_SOURCES_CACHE_KEY)
    invalidate_json_cache(TRENDING_CROSS_PLATFORM_CACHE_PREFIX)
    invalidate_json_cache(TRENDING_PERSISTENT_CACHE_PREFIX)
