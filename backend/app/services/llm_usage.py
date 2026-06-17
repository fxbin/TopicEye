from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass
from typing import Optional, Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LlmCallLog, LlmModel

logger = logging.getLogger(__name__)
LLM_USAGE_LOG_RETRY_ATTEMPTS = 6
LLM_USAGE_LOG_RETRY_BASE_DELAY = 0.25


@dataclass(frozen=True)
class TokenUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    actual_model: Optional[str] = None


@dataclass(frozen=True)
class CostBreakdown:
    billable_input_tokens: int
    input_cost: float
    output_cost: float
    cache_read_cost: float
    cache_creation_cost: float
    total_cost: float
    cost_per_1m_input: Optional[float]
    cost_per_1m_output: Optional[float]
    cost_per_1m_input_cache_hit: Optional[float]
    cost_per_1m_input_cache_create: Optional[float]


def _get_value(obj: Any, *names: str) -> Any:
    for name in names:
        if isinstance(obj, dict) and name in obj:
            return obj[name]
        if hasattr(obj, name):
            return getattr(obj, name)
    return None


def _to_int(value: Any) -> int:
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def extract_usage(response: Any) -> TokenUsage:
    usage = _get_value(response, "usage", "usageMetadata")
    actual_model = _get_value(response, "model")
    if usage is None:
        return TokenUsage(actual_model=actual_model)

    prompt_details = _get_value(usage, "prompt_tokens_details", "input_tokens_details") or {}
    input_tokens = _to_int(
        _get_value(
            usage,
            "prompt_tokens",
            "input_tokens",
            "promptTokenCount",
        )
    )
    output_tokens = _to_int(
        _get_value(
            usage,
            "completion_tokens",
            "output_tokens",
            "candidatesTokenCount",
        )
    )
    if output_tokens == 0:
        total_tokens = _to_int(_get_value(usage, "total_tokens", "totalTokenCount"))
        if total_tokens and input_tokens:
            output_tokens = max(total_tokens - input_tokens, 0)

    cache_read_tokens = _to_int(
        _get_value(
            usage,
            "cache_read_input_tokens",
            "cachedContentTokenCount",
        )
    )
    if cache_read_tokens == 0:
        cache_read_tokens = _to_int(
            _get_value(
                prompt_details,
                "cached_tokens",
                "cache_read_input_tokens",
                "cache_read_tokens",
            )
        )

    cache_creation_tokens = _to_int(
        _get_value(
            usage,
            "cache_creation_input_tokens",
            "cache_creation_tokens",
        )
    )
    if cache_creation_tokens == 0:
        cache_creation_tokens = _to_int(
            _get_value(
                prompt_details,
                "cache_creation_input_tokens",
                "cache_creation_tokens",
            )
        )

    return TokenUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_creation_tokens=cache_creation_tokens,
        actual_model=str(actual_model) if actual_model else None,
    )


def pricing_from_model(model: Optional[LlmModel]) -> dict[str, Optional[float]]:
    from app.services.llm.model_pricing import normalized_model_pricing

    if model is None:
        return {
            "input": None,
            "output": None,
            "cache_hit": None,
            "cache_create": None,
        }

    pricing = normalized_model_pricing(model)
    extra_params = model.extra_params if isinstance(model.extra_params, dict) else {}
    cache_create = _to_float(extra_params.get("cost_per_1m_input_cache_create"))
    return {
        "input": pricing["cost_per_1m_input"],
        "output": pricing["cost_per_1m_output"],
        "cache_hit": pricing["cost_per_1m_input_cache_hit"],
        "cache_create": cache_create,
    }


def _input_tokens_include_cache(provider: Optional[str], request_model: Optional[str]) -> bool:
    marker = f"{provider or ''}/{request_model or ''}".lower()
    if "anthropic" in marker or "claude" in marker:
        return False
    return True


def calculate_cost(
    usage: TokenUsage,
    pricing: dict[str, Optional[float]],
    *,
    provider: Optional[str] = None,
    request_model: Optional[str] = None,
) -> CostBreakdown:
    cost_per_1m_input = pricing.get("input") or 0.0
    cost_per_1m_output = pricing.get("output") or 0.0
    cost_per_1m_cache_hit = pricing.get("cache_hit")
    cost_per_1m_cache_create = pricing.get("cache_create")

    if _input_tokens_include_cache(provider, request_model):
        billable_input_tokens = max(usage.input_tokens - usage.cache_read_tokens, 0)
    else:
        billable_input_tokens = usage.input_tokens

    input_cost = billable_input_tokens * cost_per_1m_input / 1_000_000
    output_cost = usage.output_tokens * cost_per_1m_output / 1_000_000
    cache_read_cost = usage.cache_read_tokens * (cost_per_1m_cache_hit or 0.0) / 1_000_000
    cache_creation_cost = usage.cache_creation_tokens * (cost_per_1m_cache_create or cost_per_1m_input) / 1_000_000
    total_cost = input_cost + output_cost + cache_read_cost + cache_creation_cost

    return CostBreakdown(
        billable_input_tokens=billable_input_tokens,
        input_cost=round(input_cost, 8),
        output_cost=round(output_cost, 8),
        cache_read_cost=round(cache_read_cost, 8),
        cache_creation_cost=round(cache_creation_cost, 8),
        total_cost=round(total_cost, 8),
        cost_per_1m_input=pricing.get("input"),
        cost_per_1m_output=pricing.get("output"),
        cost_per_1m_input_cache_hit=cost_per_1m_cache_hit,
        cost_per_1m_input_cache_create=cost_per_1m_cache_create,
    )


async def record_llm_call(
    db: AsyncSession,
    *,
    model: Optional[LlmModel],
    request_model: Optional[str],
    scene: str,
    status: str,
    duration_ms: int = 0,
    usage: Optional[TokenUsage] = None,
    error_message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> LlmCallLog:
    usage = usage or TokenUsage()
    resolved_request_id = request_id or f"llm_{uuid.uuid4().hex}"
    pricing = pricing_from_model(model)
    costs = calculate_cost(
        usage,
        pricing,
        provider=model.provider if model else None,
        request_model=request_model,
    )
    payload = {
        "model_id": model.id if model else None,
        "model_name": model.name if model else None,
        "provider": model.provider if model else None,
        "request_model": request_model,
        "actual_model": usage.actual_model or request_model,
        "scene": scene,
        "status": status,
        "error_message": error_message[:2000] if error_message else None,
        "duration_ms": duration_ms,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_creation_tokens": usage.cache_creation_tokens,
        "billable_input_tokens": costs.billable_input_tokens,
        "input_cost": costs.input_cost,
        "output_cost": costs.output_cost,
        "cache_read_cost": costs.cache_read_cost,
        "cache_creation_cost": costs.cache_creation_cost,
        "total_cost": costs.total_cost,
        "cost_per_1m_input": costs.cost_per_1m_input,
        "cost_per_1m_output": costs.cost_per_1m_output,
        "cost_per_1m_input_cache_hit": costs.cost_per_1m_input_cache_hit,
        "cost_per_1m_input_cache_create": costs.cost_per_1m_input_cache_create,
    }
    existing = await db.scalar(select(LlmCallLog).where(LlmCallLog.request_id == resolved_request_id))
    if existing is not None:
        for key, value in payload.items():
            setattr(existing, key, value)
        await db.flush()
        return existing

    log = LlmCallLog(request_id=resolved_request_id, **payload)
    db.add(log)
    try:
        await db.flush()
        return log
    except IntegrityError:
        await db.rollback()
        existing = await db.scalar(select(LlmCallLog).where(LlmCallLog.request_id == resolved_request_id))
        if existing is None:
            raise
        for key, value in payload.items():
            setattr(existing, key, value)
        await db.flush()
        return existing


async def record_llm_call_in_new_session(
    *,
    model: Optional[LlmModel],
    request_model: Optional[str],
    scene: str,
    status: str,
    duration_ms: int = 0,
    usage: Optional[TokenUsage] = None,
    error_message: Optional[str] = None,
    request_id: Optional[str] = None,
) -> None:
    from app.core.database import async_session
    from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked

    async with async_session() as db:

        async def _write():
            await begin_immediate_for_sqlite(db)
            await record_llm_call(
                db,
                model=model,
                request_model=request_model,
                scene=scene,
                status=status,
                duration_ms=duration_ms,
                usage=usage,
                error_message=error_message,
                request_id=request_id,
            )
            await db.commit()

        try:
            await retry_sqlite_locked(
                _write,
                attempts=LLM_USAGE_LOG_RETRY_ATTEMPTS,
                base_delay=LLM_USAGE_LOG_RETRY_BASE_DELAY,
                on_retry=db.rollback,
            )
        except Exception as exc:
            await db.rollback()
            logger.warning("LLM usage log skipped: %s", exc)
