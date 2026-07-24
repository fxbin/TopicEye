from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json


CONTENT_LIST_CACHE_PREFIX = "contents:list:"
CACHEABLE_CONTENT_SORTS = {"created_at", "published_at", "crawled_at"}
# Match the default home-screen request exactly so startup warmup is reusable.
HOME_CONTENT_LIST_CACHE_LABEL = "contents:list:1:40:24"
HOME_CONTENT_LIST_INITIAL_PAGE_SIZE = 40


@dataclass(frozen=True)
class ContentListCacheParams:
    page: int
    page_size: int
    source_type: str | None = None
    platform: str | None = None
    status: str | None = None
    category: str | None = None
    keyword: str | None = None
    q: str | None = None
    source_id: int | None = None
    include_trend_sources: bool = False
    hours: int | None = None
    sort_by: str = "created_at"
    sort_order: str = "desc"
    user_id: int | None = None  # None = anonymous (public-only), int = user-scoped

    @property
    def cacheable(self) -> bool:
        return self.sort_by in CACHEABLE_CONTENT_SORTS

    @property
    def key(self) -> str:
        params = {
            "page": self.page,
            "page_size": self.page_size,
            "include_trend_sources": int(self.include_trend_sources),
            "sort_by": self.sort_by,
            "sort_order": self.sort_order,
            "user_id": "" if self.user_id is None else str(self.user_id),
        }
        optional = {
            "source_type": self.source_type,
            "platform": self.platform,
            "status": self.status,
            "category": self.category,
            "keyword": (self.keyword or "").strip(),
            "q": (self.q or "").strip(),
            "source_id": self.source_id,
            "hours": self.hours,
        }
        params.update({key: value for key, value in optional.items() if value not in (None, "")})
        return CONTENT_LIST_CACHE_PREFIX + urlencode(params)


def home_content_list_cache_params() -> ContentListCacheParams:
    return ContentListCacheParams(page=1, page_size=HOME_CONTENT_LIST_INITIAL_PAGE_SIZE, hours=24)


def get_cached_content_list(params: ContentListCacheParams, *, ttl_seconds: float):
    if not params.cacheable:
        return None
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_content_list(params: ContentListCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def invalidate_content_list_cache() -> None:
    invalidate_json_cache(CONTENT_LIST_CACHE_PREFIX)
