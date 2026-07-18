"""Favorite cache helpers — delegates to json_cache to avoid duplicate cache state.

Previously this module maintained its own ``_CACHE`` dict, duplicating
``json_cache.py``.  Now it wraps ``json_cache`` with a ``favorites:`` prefix
and a fixed 10-second TTL.
"""

from __future__ import annotations

from typing import Any

from app.services.json_cache import (
    get_cached_json as _get_cached_json,
    invalidate_json_cache,
    set_cached_json as _set_cached_json,
)

FAVORITE_CACHE_TTL_SECONDS = 10.0
FAVORITE_CACHE_PREFIX = "favorites:"


def get_cached_json(cache_key: str) -> tuple[bytes, float] | None:
    """Read from the shared json_cache with favorite TTL (10 s)."""
    return _get_cached_json(FAVORITE_CACHE_PREFIX + cache_key, ttl_seconds=FAVORITE_CACHE_TTL_SECONDS)


def set_cached_json(cache_key: str, payload: dict[str, Any]) -> bytes:
    """Write to the shared json_cache under the favorites prefix."""
    return _set_cached_json(FAVORITE_CACHE_PREFIX + cache_key, payload)


def invalidate_favorite_cache() -> None:
    """Invalidate all favorite cache entries."""
    invalidate_json_cache(FAVORITE_CACHE_PREFIX)


# ── Serialization helpers (business logic, not cache) ──────────


def favorite_to_dict(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "user_id": item.user_id,
        "target_type": _enum_value(item.target_type),
        "target_id": item.target_id,
        "target_key": item.target_key,
        "title": item.title,
        "url": item.url,
        "cover_url": item.cover_url,
        "source_name": item.source_name,
        "collection_id": item.collection_id,
        "tags": item.tags,
        "note": item.note,
        "status": _enum_value(item.status),
        "position": item.position,
        "snapshot": item.snapshot,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _enum_value(value: Any) -> Any:
    return getattr(value, "value", value)
