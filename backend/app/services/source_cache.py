from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json


SOURCE_LIST_CACHE_PREFIX = "sources:list:"
SOURCE_LIST_DEFAULT_CACHE_LABEL = "sources:list:1:20"


@dataclass(frozen=True)
class SourceListCacheParams:
    page: int
    page_size: int
    source_type: str | None = None
    status: str | None = None
    enabled: bool | None = None
    keyword: str | None = None
    user_id: int | None = None  # None = admin/global, int = user-scoped /me

    @property
    def key(self) -> str:
        params = {"page": self.page, "page_size": self.page_size}
        optional = {
            "source_type": self.source_type,
            "status": self.status,
            "enabled": None if self.enabled is None else int(self.enabled),
            "keyword": (self.keyword or "").strip(),
            "user_id": "" if self.user_id is None else str(self.user_id),
        }
        params.update({key: value for key, value in optional.items() if value not in (None, "")})
        return SOURCE_LIST_CACHE_PREFIX + urlencode(params)


def default_source_list_cache_params() -> SourceListCacheParams:
    return SourceListCacheParams(page=1, page_size=20)


def get_cached_source_list(params: SourceListCacheParams, *, ttl_seconds: float):
    return get_cached_json(params.key, ttl_seconds=ttl_seconds)


def set_cached_source_list(params: SourceListCacheParams, payload: dict) -> bytes:
    return set_cached_json(params.key, payload)


def invalidate_source_list_cache() -> None:
    invalidate_json_cache(SOURCE_LIST_CACHE_PREFIX)
