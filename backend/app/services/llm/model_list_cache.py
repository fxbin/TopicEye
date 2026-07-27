"""Read cache for LLM model configuration lists."""

from __future__ import annotations

from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json

MODEL_LIST_CACHE_KEY = "models:list"
MODEL_LIST_CACHE_HEADER = "X-Models-Cache"


def get_cached_model_list(*, ttl_seconds: float):
    return get_cached_json(MODEL_LIST_CACHE_KEY, ttl_seconds=ttl_seconds)


def set_cached_model_list(payload: dict) -> bytes:
    return set_cached_json(MODEL_LIST_CACHE_KEY, payload)


def invalidate_model_list_cache() -> None:
    invalidate_json_cache(MODEL_LIST_CACHE_KEY)
