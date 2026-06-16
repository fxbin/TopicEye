"""
LLM response cache 单元测试。

覆盖：set / get / miss / TTL 过期 / 大小限制淘汰。
"""
from __future__ import annotations

import time

import pytest

from app.services.llm.response_cache import LLMCache, get_llm_cache


def test_cache_set_get_hit():
    cache = LLMCache()
    msgs = [{"role": "user", "content": "hello"}]
    cache.set(msgs, 0.3, 100, model=None, raw_response='{"ok": true}')
    assert cache.get(msgs, 0.3, 100, model=None) == '{"ok": true}'
    s = cache.status()
    assert s["hits"] == 1
    assert s["misses"] == 0
    assert s["stores"] == 1


def test_cache_miss():
    cache = LLMCache()
    assert cache.get([{"role": "user", "content": "x"}], 0.3, 100, None) is None
    s = cache.status()
    assert s["misses"] == 1
    assert s["hits"] == 0


def test_cache_key_differentiation():
    """Same messages but different temperature / max_tokens → different cache keys."""
    cache = LLMCache()
    msgs = [{"role": "user", "content": "hello"}]
    cache.set(msgs, 0.0, 100, None, raw_response="deterministic")
    cache.set(msgs, 0.9, 100, None, raw_response="creative")

    assert cache.get(msgs, 0.0, 100, None) == "deterministic"
    assert cache.get(msgs, 0.9, 100, None) == "creative"


def test_cache_ttl_expiry():
    cache = LLMCache(default_ttl_seconds=0)  # immediate expiry
    msgs = [{"role": "user", "content": "hi"}]
    cache.set(msgs, 0.3, 100, None, raw_response="x", ttl_seconds=0)
    time.sleep(0.01)
    assert cache.get(msgs, 0.3, 100, None) is None


def test_cache_does_not_store_empty():
    cache = LLMCache()
    cache.set([{"role": "user", "content": "x"}], 0.3, 100, None, raw_response="")
    assert cache.get([{"role": "user", "content": "x"}], 0.3, 100, None) is None
    assert cache.status()["stores"] == 0


def test_cache_eviction_when_full():
    cache = LLMCache(max_entries=10)
    # Insert 20 entries with different contents
    for i in range(20):
        cache.set([{"role": "user", "content": f"q{i}"}], 0.3, 100, None,
                  raw_response=f"r{i}", ttl_seconds=3600)
    # Should have evicted oldest to stay under cap
    assert cache.status()["entries"] <= 10


def test_global_singleton():
    """get_llm_cache returns the same instance."""
    a = get_llm_cache()
    b = get_llm_cache()
    assert a is b
