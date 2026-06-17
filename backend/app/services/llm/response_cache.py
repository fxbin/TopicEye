"""
LLM 响应缓存（按 prompt 内容 hash）。

相同 (messages, model, temperature) 的 LLM 调用在 TTL 内返回缓存结果。
场景：
- 重试/失败的源再次抓取（same content → same LLM input）
- 重复内容（hash 撞车）→ 直接命中

注意：缓存按 (model, temperature, messages_hash) 维度，避免不同
temperature 命中相同缓存。温度 0 (deterministic) 缓存收益最大。

单进程内存实现。生产多实例需换 Redis（key 一样）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class LLMCache:
    """简单内存 LLM 响应缓存。"""

    def __init__(self, *, default_ttl_seconds: int = 86400, max_entries: int = 5000):
        self.default_ttl = default_ttl_seconds
        self.max_entries = max_entries

        # value: (raw_response, expires_at)
        self._cache: dict[str, tuple[str, float]] = {}
        self._hits = 0
        self._misses = 0
        self._stores = 0

    @staticmethod
    def _key(messages: list, temperature: float, max_tokens: int, model: str | None) -> str:
        payload = {
            "model": model or "",
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
        }
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    def get(
        self,
        messages: list,
        temperature: float,
        max_tokens: int,
        model: str | None,
        ttl_seconds: Optional[int] = None,
    ) -> Optional[str]:
        """Return cached raw response, or None on miss / expiry."""
        key = self._key(messages, temperature, max_tokens, model)
        entry = self._cache.get(key)
        if entry is None:
            self._misses += 1
            return None
        raw, expires_at = entry
        if expires_at < time.monotonic():
            self._cache.pop(key, None)
            self._misses += 1
            return None
        self._hits += 1
        logger.debug("LLM cache hit: key=%s…", key[:8])
        return raw

    def set(
        self,
        messages: list,
        temperature: float,
        max_tokens: int,
        model: str | None,
        raw_response: str,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store raw response under the cache key."""
        if not raw_response:
            return  # don't cache empty responses
        key = self._key(messages, temperature, max_tokens, model)
        ttl = ttl_seconds or self.default_ttl
        self._cache[key] = (raw_response, time.monotonic() + ttl)
        self._stores += 1
        # Evict oldest entries if over cap
        if len(self._cache) > self.max_entries:
            self._evict_oldest()

    def _evict_oldest(self) -> None:
        # Evict ~10% of oldest entries to amortize
        target = int(self.max_entries * 0.9)
        if len(self._cache) <= target:
            return
        sorted_items = sorted(self._cache.items(), key=lambda kv: kv[1][1])
        for k, _ in sorted_items[: len(self._cache) - target]:
            self._cache.pop(k, None)

    def status(self) -> dict:
        """Snapshot for /metrics / health."""
        return {
            "entries": len(self._cache),
            "max_entries": self.max_entries,
            "hits": self._hits,
            "misses": self._misses,
            "stores": self._stores,
            "hit_rate": round(self._hits / max(1, self._hits + self._misses), 4),
        }

    def clear(self) -> None:
        self._cache.clear()


# Global singleton
_cache: LLMCache | None = None


def get_llm_cache() -> LLMCache:
    global _cache
    if _cache is None:
        _cache = LLMCache()
    return _cache
