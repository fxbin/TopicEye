from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlencode

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json

# Bump the read-model cache namespace whenever a response-shaping change
# would make an older serialized payload unsafe or misleading to display.
# This prevents pre-cleanup AI summaries from being served until their TTL.
TODAY_PICKS_LEGACY_CACHE_PREFIX = "contents:today-picks:"
TODAY_PICKS_CACHE_PREFIX = "contents:today-picks:v2:"
# The page opens on the rolling 24-hour window and requests the first 40 picks.
# Keep the startup warmup key identical so the first visit can hit the cache.
TODAY_PICKS_DEFAULT_CACHE_LABEL = "contents:today-picks:v2:hours=24&limit=40"
TODAY_PICKS_INITIAL_LIMIT = 40


@dataclass(frozen=True)
class TodayPicksCacheParams:
    hours: int = 48
    category: str | None = None
    limit: int | None = None
    # None = anonymous public pool; int = public pool plus this user's private content.
    user_id: int | None = None

    @property
    def key(self) -> str:
        params = {"hours": self.hours}
        if self.category:
            params["category"] = self.category
        if self.limit:
            params["limit"] = self.limit
        params["user_id"] = "" if self.user_id is None else str(self.user_id)
        return TODAY_PICKS_CACHE_PREFIX + urlencode(params)


def default_today_picks_cache_params() -> TodayPicksCacheParams:
    return TodayPicksCacheParams(hours=24, limit=TODAY_PICKS_INITIAL_LIMIT)


def get_cached_today_picks(params: TodayPicksCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_today_picks(params: TodayPicksCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def invalidate_today_picks_cache() -> None:
    # The legacy prefix includes v2 too, so one invalidation clears stale
    # pre-cleanup payloads during rollout as well as the active cache keys.
    invalidate_json_cache(TODAY_PICKS_LEGACY_CACHE_PREFIX)
