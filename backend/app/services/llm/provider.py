"""
LLM service layer — unified AI calls via litellm.

Features:
- Ordered DB-backed route chain with automatic failover
- Per-route cooldown and recovery checks
- Rate limiting (token bucket)
- Retry with exponential backoff
- Structured JSON output parsing
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from litellm import completion
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.services.llm.model_resolver import resolve_litellm_model
from app.services.llm_usage import extract_usage, record_llm_call_in_new_session

logger = logging.getLogger(__name__)

LITELLM_COMPLETION_PARAM_KEYS = {
    "api_version",
    "custom_llm_provider",
    "default_headers",
    "drop_params",
    "extra_headers",
    "extra_query",
    "metadata",
    "num_retries",
    "organization",
    "timeout",
}


def _litellm_extra_kwargs(model_config: Any = None) -> dict[str, Any]:
    """Return explicitly configured LiteLLM kwargs from model.extra_params."""
    extra_params = getattr(model_config, "extra_params", None)
    if not isinstance(extra_params, dict):
        return {}
    litellm_params = extra_params.get("litellm_params")
    if not isinstance(litellm_params, dict):
        return {}
    return {
        key: value
        for key, value in litellm_params.items()
        if key in LITELLM_COMPLETION_PARAM_KEYS and value is not None
    }


# ── DB-backed model config cache ──────────────────────────────────────

class ModelConfigCache:
    """
    Caches enabled model route configs from DB.
    Refreshes every 60 seconds so changes in the UI take effect quickly.
    """
    def __init__(self):
        self._route_models: list[Any] = []
        self._user_route_models: dict[int, list[Any]] = {}
        self._last_refresh = 0.0
        self._user_last_refresh: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def refresh(self, user_id: int | None = None):
        """Reload model configs from DB."""
        try:
            from sqlalchemy import select

            from app.core.database import async_session
            from app.models.llm_model import LlmModel
            from app.models.user import User
            from app.services.plan_catalog import plan_allows_custom_ai

            async with async_session() as session:
                filters = [LlmModel.enabled == True]
                if user_id is None:
                    filters.append(LlmModel.owner_user_id.is_(None))
                else:
                    plan = await session.scalar(select(User.plan).where(User.id == user_id))
                    if not plan_allows_custom_ai(plan):
                        self._user_route_models[user_id] = []
                        self._user_last_refresh[user_id] = time.monotonic()
                        return
                    filters.append(LlmModel.owner_user_id == user_id)
                result = await session.execute(
                    select(LlmModel)
                    .where(*filters)
                    .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
                )
                models = result.scalars().all()

                if user_id is None:
                    self._route_models = list(models)
                    self._last_refresh = time.monotonic()
                    logger.debug("ModelConfigCache: %d system route models loaded", len(models))
                else:
                    self._user_route_models[user_id] = list(models)
                    self._user_last_refresh[user_id] = time.monotonic()
                    logger.debug("ModelConfigCache: %d user route models loaded for user=%s", len(models), user_id)
        except Exception as e:
            logger.warning("ModelConfigCache refresh failed: %s", e)

    async def _get_system_route_models(self, routing_group: str = "default"):
        now = time.monotonic()
        if now - self._last_refresh > 60:
            async with self._lock:
                if time.monotonic() - self._last_refresh > 60:
                    await self.refresh()
        group = (routing_group or "default").strip() or "default"
        models = [m for m in self._route_models if (m.routing_group or "default") == group]
        if models:
            return models
        return self._route_models

    async def _get_user_route_models(self, user_id: int, routing_group: str = "default"):
        now = time.monotonic()
        if now - self._user_last_refresh.get(user_id, 0.0) > 60:
            async with self._lock:
                if time.monotonic() - self._user_last_refresh.get(user_id, 0.0) > 60:
                    await self.refresh(user_id=user_id)
        group = (routing_group or "default").strip() or "default"
        user_models = self._user_route_models.get(user_id, [])
        models = [m for m in user_models if (m.routing_group or "default") == group]
        if models:
            return models
        return user_models

    async def get_route_models(self, routing_group: str = "default", user_id: int | None = None):
        system_models = await self._get_system_route_models(routing_group)
        if user_id is None:
            return system_models
        user_models = await self._get_user_route_models(user_id, routing_group)
        return [*user_models, *system_models]


_model_cache = ModelConfigCache()


async def invalidate_model_cache() -> None:
    """Force the next LLM call to reload model settings from the database."""
    async with _model_cache._lock:
        _model_cache._route_models = []
        _model_cache._user_route_models = {}
        _model_cache._last_refresh = 0.0
        _model_cache._user_last_refresh = {}
    reset_model_rate_limiters()
    _failover.reset()

# ── Model failover state tracker ──────────────────────────────────────

class ModelFailover:
    """
    Tracks per-model health and manages automatic failover chains.

    States:
    - HEALTHY: model is working normally
    - DEGRADED: model failed, skip until its reset time
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"

    def __init__(self):
        self._cooldowns: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def on_failure(self, key: str, *, reset_at: datetime | None = None, cooldown_seconds: int = 300):
        """Called when a model fails. Pass reset_at if the provider supplied one."""
        cooldown = max(cooldown_seconds or 300, 1)
        effective_reset = reset_at or (datetime.now(UTC) + timedelta(seconds=cooldown))
        with self._lock:
            self._cooldowns[key] = effective_reset
        logger.warning("ModelFailover: %s degraded until %s", key, effective_reset)

    def on_success(self, key: str):
        """Called after a successful LLM call."""
        with self._lock:
            if key in self._cooldowns:
                logger.info("ModelFailover: %s recovered", key)
                self._cooldowns.pop(key, None)

    def reset(self):
        """Reset failover state after model configuration changes."""
        with self._lock:
            self._cooldowns.clear()

    def should_skip(self, key: str) -> bool:
        """Return True if this model is still cooling down."""
        with self._lock:
            reset_at = self._cooldowns.get(key)
            if not reset_at:
                return False
            if datetime.now(UTC) < reset_at:
                return True
            logger.info("ModelFailover: cooldown passed, trying %s", key)
            self._cooldowns.pop(key, None)
            return False


# Global failover tracker
_failover = ModelFailover()


def _model_key(model_config: Any) -> str:
    return f"db:{model_config.id}"


def _candidate_from_db_model(model_config: Any, temperature: float, max_tokens: int) -> dict[str, Any]:
    return {
        "request_model": resolve_litellm_model(model_config),
        "api_key": model_config.api_key,
        "api_base": model_config.api_base,
        "temperature": temperature if temperature is not None else model_config.temperature,
        "max_tokens": max_tokens if max_tokens is not None else model_config.max_tokens,
        "model_config": model_config,
        "cooldown_seconds": model_config.cooldown_seconds or 300,
    }


# ── Rate limiter (simple token bucket) ────────────────────────────────

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


# ── LLM call wrapper ──────────────────────────────────────────────────

def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect if an exception is a rate limit (429) error."""
    msg = str(exc).lower()
    return any(k in msg for k in ["429", "rate limit", "rate_limit", "quota exceeded",
                                   "请求过于频繁", "调用额度", "额度用完", "已达"])


def _parse_reset_time(exc: Exception) -> datetime | None:
    """Parse the exact reset time from a rate limit error message.

    Handles formats like:
    - "您的限额将在 2026-05-18 21:11:16 重置"
    - "...reset at 2026-05-18T21:11:16..."
    Returns UTC datetime or None if not parseable.
    """
    import re
    msg = str(exc)
    # Match Chinese format: "2026-05-18 21:11:16"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})", msg)
    if m:
        try:
            dt = datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                         int(m.group(4)), int(m.group(5)), int(m.group(6)))
            # Chinese servers are likely CST (UTC+8)
            from datetime import timedelta, timezone
            cst = timezone(timedelta(hours=8))
            dt = dt.replace(tzinfo=cst)
            return dt.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


async def _call_llm_single(
    messages: list,
    model: str,
    api_key: str | None,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict | None,
    model_config: Any = None,
    scene: str = "general",
) -> str:
    """Make a single LLM call (no retry)."""
    await _rate_limiter.acquire()
    model_limiter = _get_model_rate_limiter(model_config)
    if model_limiter is not None:
        await model_limiter.acquire()

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    kwargs.update(_litellm_extra_kwargs(model_config))
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if response_format:
        kwargs["response_format"] = response_format

    logger.info("LLM call: model=%s, messages=%d", model, len(messages))

    start = time.monotonic()
    try:
        async with _get_completion_semaphore():
            response = await asyncio.to_thread(completion, **kwargs)
        duration_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content
        await record_llm_call_in_new_session(
            model=model_config,
            request_model=model,
            scene=scene,
            status="DONE",
            duration_ms=duration_ms,
            usage=extract_usage(response),
        )
        logger.info("LLM response: %d chars", len(content) if content else 0)
        return content or ""
    except Exception as exc:
        duration_ms = int((time.monotonic() - start) * 1000)
        await record_llm_call_in_new_session(
            model=model_config,
            request_model=model,
            scene=scene,
            status="FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
        )
        raise


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception_type((Exception,)),
    reraise=True,
)
async def _call_with_retry(
    messages: list,
    model: str,
    api_key: str | None,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict | None,
    model_config: Any = None,
    scene: str = "general",
) -> str:
    """Call LLM with a short retry on failure (not rate limit)."""
    return await _call_llm_single(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    )


async def call_llm_with_metadata(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    user_id: int | None = None,
    routing_group: str = "default",
) -> tuple[str, dict[str, Any]]:
    """Call LLM with automatic ordered failover and return the selected route metadata."""
    # Circuit breaker: skip LLM call entirely when in OPEN state
    from app.services.llm.circuit_breaker import get_llm_circuit_breaker
    breaker = get_llm_circuit_breaker()
    if not await breaker.allow_request():
        from app.services.llm.circuit_breaker import CircuitOpenError
        raise CircuitOpenError(
            f"LLM circuit breaker OPEN (failures={breaker.status()['failure_count']}); "
            f"callers should use fallback"
        )

    # Response cache: same (messages, temperature, model) → return cached raw
    from app.services.llm.response_cache import get_llm_cache
    cache = get_llm_cache()
    cached = cache.get(messages, temperature, max_tokens, model=None)
    if cached is not None:
        return cached, {"cache_hit": True}

    try:
        result = await _call_llm_with_metadata_inner(
            messages, temperature, max_tokens, scene, user_id, routing_group,
        )
        await breaker.record_success()
        cache.set(
            messages, temperature, max_tokens, model=None,
            raw_response=result[0],
        )
        return result
    except Exception as exc:
        # Only count genuine LLM/API failures, not caller-side issues
        from app.services.llm.circuit_breaker import CircuitOpenError
        if not isinstance(exc, CircuitOpenError):
            await breaker.record_failure()
        raise


async def _call_llm_with_metadata_inner(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    user_id: int | None = None,
    routing_group: str = "default",
) -> tuple[str, dict[str, Any]]:
    """Call LLM with automatic ordered failover and return the selected route metadata."""
    db_models = await _model_cache.get_route_models(routing_group, user_id=user_id)
    candidates = [_candidate_from_db_model(m, temperature, max_tokens) for m in db_models]

    skipped: list[dict[str, Any]] = []
    last_exc: Exception | None = None

    for candidate in candidates:
        model_config = candidate["model_config"]
        request_model = candidate["request_model"]
        api_base = candidate["api_base"]
        key = _model_key(model_config)
        if _failover.should_skip(key):
            skipped.append(candidate)
            continue

        try:
            logger.info("Calling LLM candidate: %s", request_model)
            response = await _call_with_retry(
                messages,
                request_model,
                candidate["api_key"],
                api_base,
                candidate["temperature"],
                candidate["max_tokens"],
                None,
                model_config,
                scene,
            )
            _failover.on_success(key)
            return response, _llm_call_metadata(model_config, request_model, routing_group)
        except Exception as exc:
            last_exc = exc
            reset_time = _parse_reset_time(exc) if _is_rate_limit_error(exc) else None
            _failover.on_failure(
                key,
                reset_at=reset_time,
                cooldown_seconds=candidate["cooldown_seconds"],
            )
            if _is_rate_limit_error(exc):
                logger.warning("LLM candidate rate-limited, trying next: %s", exc)
            else:
                logger.warning("LLM candidate failed, trying next: %s", exc)

    if skipped:
        logger.info("All active LLM candidates failed or were cooling down; probing skipped candidates")
        for candidate in skipped:
            model_config = candidate["model_config"]
            request_model = candidate["request_model"]
            api_base = candidate["api_base"]
            try:
                response = await _call_with_retry(
                    messages,
                    request_model,
                    candidate["api_key"],
                    api_base,
                    candidate["temperature"],
                    candidate["max_tokens"],
                    None,
                    model_config,
                    scene,
                )
                _failover.on_success(_model_key(model_config))
                return response, _llm_call_metadata(model_config, request_model, routing_group)
            except Exception as exc:
                last_exc = exc

    if last_exc:
        logger.error("All LLM candidates failed: %s", last_exc)
        raise last_exc
    raise RuntimeError("No enabled LLM route models configured")


def _llm_call_metadata(model_config: Any, request_model: str, routing_group: str) -> dict[str, Any]:
    return {
        "actual_model": request_model,
        "request_model": request_model,
        "model_name": getattr(model_config, "name", None),
        "model_id": getattr(model_config, "id", None),
        "routing_group": routing_group,
    }


async def call_llm(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    user_id: int | None = None,
    routing_group: str = "default",
) -> str:
    """Call LLM with automatic ordered failover."""
    response, _metadata = await call_llm_with_metadata(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        scene=scene,
        user_id=user_id,
        routing_group=routing_group,
    )
    return response


async def call_llm_json_with_metadata(
    messages: list,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    scene: str = "general",
    user_id: int | None = None,
    routing_group: str = "default",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Call LLM, parse JSON response, and return selected route metadata."""
    raw = ""
    metadata: dict[str, Any] = {}
    max_attempts = 1 if scene == "content_analysis" else 2
    for attempt in range(max_attempts):
        raw, metadata = await call_llm_with_metadata(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            scene=scene,
            user_id=user_id,
            routing_group=routing_group,
        )

        text = raw.strip()
        if not text:
            logger.warning("LLM returned empty response (attempt %d)", attempt + 1)
            if attempt < max_attempts - 1:
                continue
            return {"raw_response": raw}, metadata

        if "```json" in text:
            start = text.index("```json") + 7
            end = text.index("```", start)
            text = text[start:end].strip()
        elif "```" in text:
            start = text.index("```") + 3
            end = text.index("```", start)
            text = text[start:end].strip()

        try:
            result = json.loads(text)
            if not isinstance(result, dict) or not result:
                logger.warning("LLM JSON is empty or not a dict (attempt %d): %s", attempt + 1, str(result)[:200])
                if attempt < max_attempts - 1:
                    continue
                return {"raw_response": raw}, metadata
            return result, metadata
        except json.JSONDecodeError:
            logger.warning("Failed to parse LLM JSON response (attempt %d): %s", attempt + 1, text[:200])
            if attempt < max_attempts - 1:
                continue

    return {"raw_response": raw}, metadata


async def call_llm_json(
    messages: list,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    scene: str = "general",
    user_id: int | None = None,
    routing_group: str = "default",
) -> dict[str, Any]:
    """Call LLM and parse JSON response."""
    result, _metadata = await call_llm_json_with_metadata(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        scene=scene,
        user_id=user_id,
        routing_group=routing_group,
    )
    return result
