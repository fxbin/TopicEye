from __future__ import annotations

from datetime import datetime
import json
import time
from typing import Any, Optional


_CACHE_TTL_SECONDS = 10.0
_CACHE: dict[str, tuple[float, bytes]] = {}


def get_cached_json(cache_key: str) -> tuple[bytes, float] | None:
    cached = _CACHE.get(cache_key)
    if not cached:
        return None
    cached_at, content = cached
    age_seconds = time.monotonic() - cached_at
    if age_seconds > _CACHE_TTL_SECONDS:
        _CACHE.pop(cache_key, None)
        return None
    return content, age_seconds


def set_cached_json(cache_key: str, payload: dict[str, Any]) -> bytes:
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default).encode("utf-8")
    _CACHE[cache_key] = (time.monotonic(), content)
    return content


def invalidate_favorite_cache() -> None:
    _CACHE.clear()


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


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)
