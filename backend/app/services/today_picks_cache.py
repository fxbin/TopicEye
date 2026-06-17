from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json


TODAY_PICKS_CACHE_PREFIX = "contents:today-picks:"
TODAY_PICKS_DEFAULT_CACHE_LABEL = "contents:today-picks:48"


@dataclass(frozen=True)
class TodayPicksCacheParams:
    hours: int = 48
    category: str | None = None
    limit: int | None = None

    @property
    def key(self) -> str:
        params = {"hours": self.hours}
        if self.category:
            params["category"] = self.category
        if self.limit:
            params["limit"] = self.limit
        return TODAY_PICKS_CACHE_PREFIX + urlencode(params)


def default_today_picks_cache_params() -> TodayPicksCacheParams:
    return TodayPicksCacheParams(hours=48)


def get_cached_today_picks(params: TodayPicksCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_today_picks(params: TodayPicksCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def invalidate_today_picks_cache() -> None:
    invalidate_json_cache(TODAY_PICKS_CACHE_PREFIX)
