from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

# 进程内 JSON 缓存：读路径 L1（trending / contents / stats / favorites 等）。
#
# 内存预算：此前是裸 dict，无上限、无清扫——高基数键（按用户/关键词/分页
# 组合的 contents:list、today_count 等）会随进程生命无限累积。set 时按
# 「条目数 + 字节总量」双预算做 FIFO 淘汰（dict 保持插入序，老键先走）。
# 注：TTL 由读取方传入（不同调用方不同），淘汰无法感知过期，只能按最老
# 写入淘汰；过期清理由读路径的惰性 pop 完成。
_MAX_ENTRIES = 2000
_MAX_TOTAL_BYTES = 64 * 1024 * 1024  # 64MB
_EVICTION_BATCH_FRACTION = 0.1  # 超预算时一次淘汰 ~10%，摊销代价

_CACHE: dict[str, tuple[float, bytes]] = {}
_TOTAL_BYTES = 0


def get_cached_json(cache_key: str, *, ttl_seconds: float) -> tuple[bytes, float] | None:
    """Return raw cached JSON bytes and age (for fast-path API responses)."""
    cached = _CACHE.get(cache_key)
    if not cached:
        return None
    cached_at, content = cached
    age_seconds = time.monotonic() - cached_at
    if age_seconds > ttl_seconds:
        _pop_entry(cache_key)
        return None
    return content, age_seconds


def get_cached_value(cache_key: str, *, ttl_seconds: float) -> tuple[Any, float] | None:
    """Return deserialized cached value and age (for in-process dict consumers)."""
    cached = _CACHE.get(cache_key)
    if not cached:
        return None
    cached_at, content = cached
    age_seconds = time.monotonic() - cached_at
    if age_seconds > ttl_seconds:
        _pop_entry(cache_key)
        return None
    return json.loads(content), age_seconds


def set_cached_json(cache_key: str, payload: Any) -> bytes:
    global _TOTAL_BYTES
    content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=_json_default).encode("utf-8")
    if cache_key not in _CACHE and (len(_CACHE) >= _MAX_ENTRIES or _TOTAL_BYTES + len(content) > _MAX_TOTAL_BYTES):
        _evict_oldest_until_space(len(content))
    _pop_entry(cache_key)
    _CACHE[cache_key] = (time.monotonic(), content)
    _TOTAL_BYTES += len(content)
    return content


def invalidate_json_cache(prefix: str | None = None) -> None:
    if prefix is None:
        _CACHE.clear()
        global _TOTAL_BYTES
        _TOTAL_BYTES = 0
        return
    for key in list(_CACHE):
        if key.startswith(prefix):
            _pop_entry(key)


def cache_stats() -> dict[str, int | float]:
    """内存占用快照（诊断 / metrics 用）。"""
    return {
        "entries": len(_CACHE),
        "max_entries": _MAX_ENTRIES,
        "total_bytes": _TOTAL_BYTES,
        "max_total_bytes": _MAX_TOTAL_BYTES,
    }


def _pop_entry(cache_key: str) -> None:
    global _TOTAL_BYTES
    entry = _CACHE.pop(cache_key, None)
    if entry is not None:
        _TOTAL_BYTES = max(0, _TOTAL_BYTES - len(entry[1]))


def _evict_oldest_until_space(incoming_bytes: int) -> None:
    """按插入序淘汰最老的条目，直到同时满足两条预算。"""
    target_entries = int(_MAX_ENTRIES * (1 - _EVICTION_BATCH_FRACTION))
    target_bytes = int(_MAX_TOTAL_BYTES * (1 - _EVICTION_BATCH_FRACTION))
    for key in list(_CACHE):
        if len(_CACHE) <= target_entries and _TOTAL_BYTES + incoming_bytes <= target_bytes:
            break
        _pop_entry(key)


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    return str(value)
