"""
LLM 调用的限流与并发控制。

- 全局令牌桶 `_rate_limiter`（按 LLM_REQUESTS_PER_MINUTE）
- 每模型令牌桶（按 model.requests_per_minute）
- 全局完成信号量（按 LLM_WORKER_CONCURRENCY）

从 provider.py 拆出，无反向依赖。
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from typing import Any

from app.config import settings

logger = logging.getLogger(__name__)


class RateLimiter:
    """Simple token-bucket rate limiter for LLM API calls."""

    def __init__(self, max_requests: int = 60, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._tokens = max_requests
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self._last_refill
            refill = int(elapsed / self.window * self.max_requests)
            if refill > 0:
                self._tokens = min(self.max_requests, self._tokens + refill)
                self._last_refill = now

            if self._tokens <= 0:
                sleep_time = self.window / self.max_requests
                logger.warning("Rate limiter: waiting %.1fs", sleep_time)
                await asyncio.sleep(sleep_time)
                self._tokens = 1
                self._last_refill = time.monotonic()

            self._tokens -= 1


# Global rate limiter
_rate_limiter = RateLimiter(
    max_requests=settings.LLM_REQUESTS_PER_MINUTE,
    window_seconds=60,
)
_model_rate_limiters: dict[str, RateLimiter] = {}
_model_rate_limiters_lock = threading.Lock()
_completion_semaphore: asyncio.Semaphore | None = None


def _normalize_llm_concurrency(value: Any = None) -> int:
    try:
        parsed = int(value if value is not None else settings.LLM_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 20))


def _normalize_model_rpm(value: Any = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(parsed, int(settings.LLM_REQUESTS_PER_MINUTE or 60)))


def _model_limiter_key(model_config: Any = None) -> str | None:
    if model_config is None:
        return None
    model_id = getattr(model_config, "id", None)
    if model_id is None:
        return None
    return f"db:{model_id}"


def _get_model_rate_limiter(model_config: Any = None) -> RateLimiter | None:
    rpm = _normalize_model_rpm(getattr(model_config, "requests_per_minute", None))
    if rpm <= 0:
        return None
    key = _model_limiter_key(model_config)
    if key is None:
        return None
    with _model_rate_limiters_lock:
        limiter = _model_rate_limiters.get(key)
        if limiter is None or limiter.max_requests != rpm:
            limiter = RateLimiter(max_requests=rpm, window_seconds=60)
            _model_rate_limiters[key] = limiter
        return limiter


def reset_model_rate_limiters() -> None:
    """Reset per-model request limiters after model configuration changes/tests."""
    with _model_rate_limiters_lock:
        _model_rate_limiters.clear()


def _get_completion_semaphore() -> asyncio.Semaphore:
    global _completion_semaphore
    limit = _normalize_llm_concurrency()
    if _completion_semaphore is None:
        _completion_semaphore = asyncio.Semaphore(limit)
    return _completion_semaphore


def reset_completion_semaphore() -> None:
    """Reset the global LLM completion concurrency gate after config changes/tests."""
    global _completion_semaphore
    _completion_semaphore = None
