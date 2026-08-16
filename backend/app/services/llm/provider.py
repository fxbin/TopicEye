"""
LLM service layer — unified AI calls via litellm.

Features:
- Ordered DB-backed route chain with automatic failover
- Per-route cooldown and recovery checks
- Rate limiting (token bucket)
- Retry with exponential backoff
- Structured JSON output parsing

本模块为编排层（facade）：
- _model_cache.py   模型配置缓存
- _failover.py      故障转移状态
- _rate_limit.py    限流与并发
- _call_engine.py   单次调用 + 重试引擎

为保持向后兼容，本文件 re-export 子模块的公共符号；外部应继续从
app.services.llm import call_llm / call_llm_json。
"""

from __future__ import annotations

import asyncio  # noqa: F401  (kept for callers importing provider-level helpers)
import json
import logging
from typing import Any

from litellm.exceptions import UnsupportedParamsError

from app.services.llm._call_engine import (
    _call_with_retry,
    _is_deterministic_request_error,
    _is_rate_limit_error,
    _parse_reset_time,
)
from app.services.llm._failover import _candidate_from_db_model, _failover, _model_key
from app.services.llm._model_cache import _model_cache
from app.services.llm._rate_limit import (
    _pool_scope,
    record_llm_pool_circuit_event,
    reset_model_rate_limiters,
    reset_token_rate_limiter,
)

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


async def invalidate_model_cache() -> None:
    """Force the next LLM call to reload model settings from the database."""
    async with _model_cache._lock:
        _model_cache._route_models = []
        _model_cache._last_refresh = 0.0
    reset_model_rate_limiters()
    reset_token_rate_limiter()
    _failover.reset()
    # 配置变更可能新增健康备用渠道；不能让旧路由组的 OPEN 状态继续阻断它。
    from app.services.llm.circuit_breaker import reset_llm_circuit_breakers

    reset_llm_circuit_breakers()
    # 模型顺序、端点或参数变更后，旧路由的结果不能继续作为命中项返回。
    from app.services.llm.response_cache import get_llm_cache

    get_llm_cache().clear()


def _cache_scope(routing_group: str, scene: str) -> str:
    """Build a cache namespace for the selected routing policy."""
    return f"routing_group:{routing_group}|scene:{scene}"


class LlmCapacityUnavailableError(Exception):
    """All enabled candidates are cooling down, with a deterministic retry time."""

    def __init__(self, *, routing_group: str, next_available_at):
        self.routing_group = routing_group
        self.next_available_at = next_available_at
        retry_at = next_available_at.isoformat() if next_available_at else "unknown"
        super().__init__(
            f"LLM route '{routing_group}' has no immediately available model; "
            f"all enabled candidates are cooling down (retry_at={retry_at})"
        )


async def call_llm_with_metadata(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    routing_group: str = "default",
    response_format: dict | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call LLM with automatic ordered failover and return the selected route metadata.

    ``response_format`` is passed through to litellm's ``acompletion``.
    When a provider does not support it (``UnsupportedParamsError``),
    the failover loop retries that candidate without ``response_format``
    so JSON-mode callers still get a usable text response.
    """
    # Circuit breaker: skip LLM call entirely when in OPEN state
    from app.services.llm.circuit_breaker import get_llm_circuit_breaker

    breaker = get_llm_circuit_breaker(routing_group)
    if not await breaker.allow_request():
        from app.services.llm.circuit_breaker import CircuitOpenError

        record_llm_pool_circuit_event(None, scene, "global_open")
        raise CircuitOpenError(
            f"LLM circuit breaker OPEN (failures={breaker.status()['failure_count']}); callers should use fallback"
        )

    # Response cache: same (messages, temperature, model) → return cached raw
    from app.services.llm.response_cache import get_llm_cache

    cache = get_llm_cache()
    cache_scope = _cache_scope(routing_group, scene)
    cached = cache.get(messages, temperature, max_tokens, model=cache_scope)
    if cached is not None:
        return cached, {"cache_hit": True}

    try:
        result = await _call_llm_with_metadata_inner(
            messages,
            temperature,
            max_tokens,
            scene,
            routing_group,
            response_format=response_format,
        )
        await breaker.record_success()
        cache.set(
            messages,
            temperature,
            max_tokens,
            model=cache_scope,
            raw_response=result[0],
        )
        return result
    except Exception as exc:
        # 输入或内容策略错误不反映模型可用性，不能污染全局熔断器。
        from app.services.llm.circuit_breaker import CircuitOpenError

        # 429 和本地候选冷却代表局部容量耗尽，由 per-model failover 管理；
        # 把它们累计到路由熔断器会让一个配额不足的渠道阻断全部调用。
        if (
            not isinstance(exc, CircuitOpenError | LlmCapacityUnavailableError)
            and not _is_deterministic_request_error(exc)
            and not _is_rate_limit_error(exc)
        ):
            await breaker.record_failure()
        raise


async def _call_llm_with_metadata_inner(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    routing_group: str = "default",
    response_format: dict | None = None,
) -> tuple[str, dict[str, Any]]:
    """Call LLM with automatic ordered failover and return the selected route metadata."""
    db_models = await _model_cache.get_route_models(routing_group)
    candidates = [_candidate_from_db_model(m, temperature, max_tokens) for m in db_models]

    skipped: list[dict[str, Any]] = []
    last_exc: Exception | None = None

    for candidate in candidates:
        model_config = candidate["model_config"]
        request_model = candidate["request_model"]
        api_base = candidate["api_base"]
        key = _model_key(model_config)
        if _failover.should_skip(key):
            record_llm_pool_circuit_event(model_config, scene, "candidate_cooling_down")
            candidate["_failover_key"] = key  # 重探时重新检查冷却用
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
                response_format,
                model_config,
                scene,
            )
            _failover.on_success(key)
            return response, _llm_call_metadata(model_config, request_model, routing_group, scene)
        except UnsupportedParamsError:
            # Provider doesn't support response_format (e.g. some GLM / DeepSeek
            # endpoints). Retry the same candidate without it so JSON-mode
            # callers still get a parseable text response. If the retry also
            # fails (rate limit / timeout / etc.), fall through to the generic
            # except block below so failover to the next candidate still works.
            logger.info("Model %s doesn't support response_format, retrying without", request_model)
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
                _failover.on_success(key)
                return response, _llm_call_metadata(model_config, request_model, routing_group, scene)
            except Exception as exc:
                last_exc = exc
                if _is_deterministic_request_error(exc):
                    logger.info("LLM request rejected; keeping route healthy: %s", exc)
                    raise
                reset_time = _parse_reset_time(exc) if _is_rate_limit_error(exc) else None
                _failover.on_failure(
                    key,
                    reset_at=reset_time,
                    cooldown_seconds=candidate["cooldown_seconds"],
                )
                record_llm_pool_circuit_event(model_config, scene, "candidate_failed")
        except Exception as exc:
            last_exc = exc
            if _is_deterministic_request_error(exc):
                logger.info("LLM request rejected; keeping route healthy: %s", exc)
                raise
            reset_time = _parse_reset_time(exc) if _is_rate_limit_error(exc) else None
            _failover.on_failure(
                key,
                reset_at=reset_time,
                cooldown_seconds=candidate["cooldown_seconds"],
            )
            record_llm_pool_circuit_event(model_config, scene, "candidate_degraded")
            if _is_rate_limit_error(exc):
                logger.warning("LLM candidate rate-limited, trying next: %s", exc)
            else:
                logger.warning("LLM candidate failed, trying next: %s", exc)

    if last_exc:
        logger.error("All LLM candidates failed: %s", last_exc)
        raise last_exc
    if skipped:
        next_available_at = _failover.next_available_at(candidate["_failover_key"] for candidate in skipped)
        logger.info(
            "All enabled LLM candidates are cooling down; routing_group=%s retry_at=%s",
            routing_group,
            next_available_at,
        )
        raise LlmCapacityUnavailableError(
            routing_group=routing_group,
            next_available_at=next_available_at,
        )
    raise RuntimeError("No enabled LLM route models configured")


def _llm_call_metadata(
    model_config: Any, request_model: str, routing_group: str, scene: str = "general"
) -> dict[str, Any]:
    return {
        "actual_model": request_model,
        "request_model": request_model,
        "model_name": getattr(model_config, "name", None),
        "model_id": getattr(model_config, "id", None),
        "routing_group": routing_group,
        "pool_scope": _pool_scope(model_config, scene),
    }


async def call_llm(
    messages: list,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    scene: str = "general",
    routing_group: str = "default",
) -> str:
    """Call LLM with automatic ordered failover."""
    response, _metadata = await call_llm_with_metadata(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        scene=scene,
        routing_group=routing_group,
    )
    return response


# Default JSON mode for all call_llm_json* callers.
_JSON_RESPONSE_FORMAT = {"type": "json_object"}


async def call_llm_json_with_metadata(
    messages: list,
    temperature: float = 0.2,
    max_tokens: int = 2000,
    scene: str = "general",
    routing_group: str = "default",
) -> tuple[dict[str, Any] | list[Any], dict[str, Any]]:
    """Call LLM, parse JSON response, and return selected route metadata.

    Accepts both JSON objects (dict) and JSON arrays (list) as valid responses.
    The translate endpoint asks the LLM to output a JSON array, so lists must
    be accepted to avoid unnecessary retries that double the call duration.
    """
    raw = ""
    metadata: dict[str, Any] = {}
    max_attempts = 1 if scene == "content_analysis" else 2
    for attempt in range(max_attempts):
        raw, metadata = await call_llm_with_metadata(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            scene=scene,
            routing_group=routing_group,
            response_format=_JSON_RESPONSE_FORMAT,
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
            if not isinstance(result, dict | list) or not result:
                logger.warning("LLM JSON is empty or not a dict/list (attempt %d): %s", attempt + 1, str(result)[:200])
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
    routing_group: str = "default",
) -> dict[str, Any] | list[Any]:
    """Call LLM and parse JSON response.

    Returns a dict for JSON objects or a list for JSON arrays.
    Callers that expect only dicts should check ``isinstance(result, dict)``
    before accessing dict-specific methods like ``.get()``.
    """
    result, _metadata = await call_llm_json_with_metadata(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
        scene=scene,
        routing_group=routing_group,
    )
    return result
