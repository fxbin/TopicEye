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
from collections import defaultdict
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.config import settings

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


class TokenRateLimiter:
    """Token-bucket limiter for the aggregate LLM token budget."""

    def __init__(self, max_tokens: int, window_seconds: float = 60):
        self.max_tokens = max(1, int(max_tokens))
        self.window_seconds = max(0.001, float(window_seconds))
        self._available = float(self.max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int) -> None:
        required = min(max(1, int(tokens)), self.max_tokens)
        while True:
            async with self._lock:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._available = min(
                    float(self.max_tokens),
                    self._available + elapsed * self.max_tokens / self.window_seconds,
                )
                self._last_refill = now
                if self._available >= required:
                    self._available -= required
                    return
                wait_seconds = (required - self._available) * self.window_seconds / self.max_tokens
            await asyncio.sleep(wait_seconds)


# Global rate limiter
_rate_limiter = RateLimiter(
    max_requests=settings.LLM_REQUESTS_PER_MINUTE,
    window_seconds=60,
)
_model_rate_limiters: dict[str, RateLimiter] = {}
_model_rate_limiters_lock = threading.Lock()
_completion_semaphore: asyncio.Semaphore | None = None
_token_rate_limiter: TokenRateLimiter | None = None
_background_completion_semaphore: asyncio.Semaphore | None = None
_pool_completion_semaphores: dict[str, asyncio.Semaphore] = {}
_pool_completion_semaphores_lock = threading.Lock()

# These scenes are normally fed by a backfill or sync batch.  Reserving one
# global completion slot prevents a long-running analysis drain from making
# user-triggered reports, summaries, and searches wait behind it.  The
# reservation applies across all model channels, not just to one model.
_BACKGROUND_SCENES = frozenset(
    {
        "content_analysis",
        "content_classification",
        "content_enrichment",
        "relation_discovery",
    }
)


class LlmPoolMetrics:
    """Low-cardinality, process-local admission telemetry for the model pool.

    Metrics deliberately use a pool scope (channel/routing group + scene),
    never prompts, API keys, or content ids.  They can be exported by a
    monitoring adapter without putting observability on the request path.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active: dict[str, int] = defaultdict(int)
        self._max_active: dict[str, int] = defaultdict(int)
        self._admitted: dict[str, int] = defaultdict(int)
        self._queue_wait_seconds: dict[str, float] = defaultdict(float)
        self._rate_limit_wait_seconds: dict[str, float] = defaultdict(float)
        self._circuit_events: dict[tuple[str, str], int] = defaultdict(int)

    def admitted(self, scope: str, wait_seconds: float) -> None:
        with self._lock:
            self._admitted[scope] += 1
            self._queue_wait_seconds[scope] += max(0.0, wait_seconds)
            self._active[scope] += 1
            self._max_active[scope] = max(self._max_active[scope], self._active[scope])

    def released(self, scope: str) -> None:
        with self._lock:
            self._active[scope] = max(0, self._active[scope] - 1)

    def rate_limited(self, scope: str, wait_seconds: float) -> None:
        with self._lock:
            self._rate_limit_wait_seconds[scope] += max(0.0, wait_seconds)

    def circuit_event(self, scope: str, event: str) -> None:
        with self._lock:
            self._circuit_events[(scope, event)] += 1

    def snapshot(self) -> dict[str, dict[str, float | int]]:
        """Return a copy suitable for a future metrics endpoint or exporter."""
        with self._lock:
            scopes = set(self._active) | set(self._admitted) | set(self._queue_wait_seconds)
            result: dict[str, dict[str, float | int]] = {
                scope: {
                    "active": self._active[scope],
                    "max_active": self._max_active[scope],
                    "admitted": self._admitted[scope],
                    "queue_wait_seconds": round(self._queue_wait_seconds[scope], 6),
                    "rate_limit_wait_seconds": round(self._rate_limit_wait_seconds[scope], 6),
                }
                for scope in sorted(scopes)
            }
            for (scope, event), count in self._circuit_events.items():
                result.setdefault(scope, {})[f"circuit_{event}_total"] = count
            return result

    def reset(self) -> None:
        with self._lock:
            self._active.clear()
            self._max_active.clear()
            self._admitted.clear()
            self._queue_wait_seconds.clear()
            self._rate_limit_wait_seconds.clear()
            self._circuit_events.clear()


_pool_metrics = LlmPoolMetrics()


def _normalize_llm_concurrency(value: Any = None) -> int:
    try:
        parsed = int(value if value is not None else settings.LLM_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 20))


def _pool_options(model_config: Any) -> dict[str, Any]:
    """Read optional pool controls from the existing JSON model config.

    No schema migration is needed: an operator can add, for example,
    ``{"pool": {"max_concurrency": 2,
    "scene_concurrency": {"daily_report": 1}}}`` to ``extra_params``.
    Unknown or malformed values intentionally fall back to safe defaults.
    """
    extra_params = getattr(model_config, "extra_params", None)
    if not isinstance(extra_params, dict):
        return {}
    pool = extra_params.get("pool")
    return pool if isinstance(pool, dict) else {}


def _pool_scope(model_config: Any, scene: str) -> str:
    """Build a bounded, operator-recognisable concurrency scope."""
    routing_group = str(getattr(model_config, "routing_group", None) or "default").strip() or "default"
    channel = str(getattr(model_config, "channel_name", None) or "").strip()
    model_id = getattr(model_config, "id", None)
    channel_or_model = channel or f"model-{model_id if model_id is not None else 'runtime'}"
    return f"route:{routing_group}|channel:{channel_or_model}|scene:{scene or 'general'}"


def _pool_concurrency_limit(model_config: Any, scene: str) -> int:
    """Resolve the per-channel/scene cap from ``extra_params.pool``.

    The global worker bound remains the hard safety limit.  By default a
    channel may use that full capacity; background work additionally goes
    through a shared reserved-slot gate below, so it cannot monopolise it.
    """
    pool = _pool_options(model_config)
    configured = None
    scene_limits = pool.get("scene_concurrency")
    if isinstance(scene_limits, dict):
        configured = scene_limits.get(scene)
    if configured is None:
        configured = pool.get("max_concurrency")
    return min(_normalize_llm_concurrency(), _normalize_llm_concurrency(configured))


def _is_background_scene(scene: str) -> bool:
    return (scene or "general").strip().lower() in _BACKGROUND_SCENES


def _get_background_completion_semaphore() -> asyncio.Semaphore:
    """Keep one global slot available for non-backfill traffic when possible."""
    global _background_completion_semaphore
    background_limit = max(1, _normalize_llm_concurrency() - 1)
    if _background_completion_semaphore is None:
        _background_completion_semaphore = asyncio.Semaphore(background_limit)
    return _background_completion_semaphore


def _get_pool_completion_semaphore(model_config: Any, scene: str) -> tuple[str, asyncio.Semaphore]:
    scope = _pool_scope(model_config, scene)
    limit = _pool_concurrency_limit(model_config, scene)
    with _pool_completion_semaphores_lock:
        semaphore = _pool_completion_semaphores.get(scope)
        # Configuration refresh invalidates the complete gate set, so a scope
        # can only be replaced while it has no waiters in normal operation.
        # Do not shrink an existing active semaphore mid-flight.
        if semaphore is None:
            semaphore = asyncio.Semaphore(limit)
            _pool_completion_semaphores[scope] = semaphore
        return scope, semaphore


def get_llm_pool_metrics() -> dict[str, dict[str, float | int]]:
    """Expose a snapshot for diagnostics and future Prometheus integration."""
    return _pool_metrics.snapshot()


def record_llm_pool_circuit_event(model_config: Any, scene: str, event: str) -> None:
    _pool_metrics.circuit_event(_pool_scope(model_config, scene), event)


@asynccontextmanager
async def acquire_completion_slot(model_config: Any, scene: str) -> AsyncIterator[None]:
    """Acquire model-channel, background-reservation and global slots fairly.

    Ordering is narrow-to-broad: requests first queue at their channel scope,
    then (only for backfills) at the shared background budget, and finally at
    the process-wide safety semaphore.  This prevents one analysis channel
    from consuming all completions while preserving the existing global cap.
    """
    scope, pool_semaphore = _get_pool_completion_semaphore(model_config, scene)
    started = time.monotonic()
    await pool_semaphore.acquire()
    background_semaphore = _get_background_completion_semaphore() if _is_background_scene(scene) else None
    global_semaphore: asyncio.Semaphore | None = None
    try:
        if background_semaphore is not None:
            await background_semaphore.acquire()
        try:
            global_semaphore = _get_completion_semaphore()
            await global_semaphore.acquire()
        except BaseException:
            if background_semaphore is not None:
                background_semaphore.release()
            raise
    except BaseException:
        pool_semaphore.release()
        raise

    _pool_metrics.admitted(scope, time.monotonic() - started)
    try:
        yield
    finally:
        # Hold the exact object acquired above: a configuration refresh may
        # install a replacement gate while an existing request is in flight.
        assert global_semaphore is not None
        global_semaphore.release()
        if background_semaphore is not None:
            background_semaphore.release()
        pool_semaphore.release()
        _pool_metrics.released(scope)


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
    """Reset completion gates after config changes/tests.

    Model-cache invalidation is the configuration boundary, so all derived
    channel and scene gates must be reset together with the global one.
    """
    global _completion_semaphore, _background_completion_semaphore
    _completion_semaphore = None
    _background_completion_semaphore = None
    with _pool_completion_semaphores_lock:
        _pool_completion_semaphores.clear()
    _pool_metrics.reset()


def _get_token_rate_limiter() -> TokenRateLimiter:
    global _token_rate_limiter
    try:
        budget = max(1, int(settings.LLM_TOKENS_PER_MINUTE))
    except (TypeError, ValueError):
        budget = 100_000
    if _token_rate_limiter is None or _token_rate_limiter.max_tokens != budget:
        _token_rate_limiter = TokenRateLimiter(budget)
    return _token_rate_limiter


def reset_token_rate_limiter() -> None:
    global _token_rate_limiter
    _token_rate_limiter = None


def estimate_request_tokens(messages: list, max_tokens: int) -> int:
    """Conservative local estimate used before a provider returns real usage."""
    prompt_chars = sum(len(str(message.get("content", ""))) for message in messages if isinstance(message, dict))
    try:
        output_budget = max(0, int(max_tokens))
    except (TypeError, ValueError):
        output_budget = 0
    return max(1, (prompt_chars + 3) // 4 + output_budget)
