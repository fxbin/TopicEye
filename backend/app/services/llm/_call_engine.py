"""
LLM 单次调用引擎（无 failover / 无路由编排）。

- 限流错误判定 `_is_rate_limit_error` / `_parse_reset_time`
- 单次调用 `_call_llm_single`（限流 + 信号量 + 用量记录）
- tenacity 重试包装 `_call_with_retry` / `_should_retry`

从 provider.py 拆出。依赖 _rate_limit 的限流原语和 llm_usage 的用量记录。
不含 failover / 路由编排（那部分留在 provider.py 的 call_llm_with_metadata）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from litellm import RateLimitError, acompletion
from litellm.exceptions import (  # noqa: I001 — litellm 子模块按 ruff isort 规则应与 litellm 同组
    BadRequestError,
    ContentPolicyViolationError,
    ContextWindowExceededError,
    JSONSchemaValidationError,
    UnprocessableEntityError,
    UnsupportedParamsError,
)
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.services.llm._rate_limit import (
    _get_model_rate_limiter,
    _get_token_rate_limiter,
    _pool_metrics,
    _pool_scope,
    _rate_limiter,
    acquire_completion_slot,
    estimate_request_tokens,
)

logger = logging.getLogger(__name__)


def _is_rate_limit_error(exc: Exception) -> bool:
    """Detect if an exception is a rate limit (429) error."""
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ["429", "rate limit", "rate_limit", "quota exceeded", "请求过于频繁", "调用额度", "额度用完", "已达"]
    )


def _is_bad_request_error(exc: Exception) -> bool:
    """Detect if an exception is a bad request (400) error.

    400 是确定性错误（请求格式错误或内容被过滤），重试不会改变结果。
    典型场景：GLM/智谱 contentFilter code=1301 触发内容安全过滤。
    """
    if isinstance(exc, BadRequestError):
        return True
    msg = str(exc).lower()
    return "error code: 400" in msg or ("contentfilter" in msg and "400" in msg)


def _is_deterministic_request_error(exc: Exception) -> bool:
    """Return whether the caller must change the request before retrying.

    这类错误与某个候选模型的健康度无关：切换模型既不能通过内容安全
    过滤，也不能缩短超出上下文窗口的输入。将它们计入模型失败会错误地
    冷却健康路由，并在所有模型都拒绝同一请求时打开全局熔断器。
    """
    from app.services.llm._context_guard import LlmContextWindowExceededError
    from app.services.llm.call_trace import LlmTraceBudgetExceeded

    if isinstance(
        exc,
        BadRequestError
        | ContentPolicyViolationError
        | ContextWindowExceededError
        | JSONSchemaValidationError
        | UnprocessableEntityError
        | UnsupportedParamsError
        | LlmContextWindowExceededError
        | LlmTraceBudgetExceeded,
    ):
        return True
    return _is_bad_request_error(exc)


def _completion_timeout_seconds(configured_timeout: Any = None) -> float:
    """Return a positive, globally bounded LLM deadline in seconds."""
    try:
        hard_cap = max(float(settings.LLM_COMPLETION_TIMEOUT_SECONDS), 0.1)
    except (TypeError, ValueError):
        hard_cap = 45.0

    if configured_timeout is None:
        return hard_cap
    try:
        return min(max(float(configured_timeout), 0.1), hard_cap)
    except (TypeError, ValueError):
        return hard_cap


def _parse_reset_time(exc: Exception):
    """Parse the exact reset time from a rate limit error message.

    Handles formats like:
    - "您的限额将在 2026-05-18 21:11:16 重置"
    - "...reset at 2026-05-18T21:11:16..."
    Returns UTC datetime or None if not parseable.
    """
    import re
    from datetime import UTC, datetime, timedelta, timezone

    msg = str(exc)
    # Match Chinese format: "2026-05-18 21:11:16"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})", msg)
    if m:
        try:
            dt = datetime(
                int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)), int(m.group(6))
            )
            # Chinese servers are likely CST (UTC+8)
            cst = timezone(timedelta(hours=8))
            dt = dt.replace(tzinfo=cst)
            return dt.astimezone(UTC)
        except (ValueError, OverflowError):
            pass
    return None


async def _complete_with_selected_transport(
    *,
    kwargs: dict[str, Any],
    messages: list,
    api_key: str | None,
    api_base: str | None,
    temperature: float,
    max_tokens: int,
    response_format: dict | None,
    model_config: Any,
    timeout: float,
):
    """按 ``LLM_TRANSPORT`` 选择传输实现，返回**读取形状一致**的响应。

    两条路径的返回对象都支持 ``response.choices[0].message.content`` 与
    ``extract_usage`` 需要的 ``.usage`` / ``.model``，因此下游（用量提取、
    计价、调用轨迹落库）无需区分传输实现。

    - ``litellm``（默认）：行为与改动前完全一致。
    - ``native``：已实现协议的 provider（OpenAI 兼容 / anthropic / gemini）
      走自有传输层；不满足条件的 provider 显式回落 litellm 并记 warning
      （不静默换路径）。
    """
    if settings.LLM_TRANSPORT.strip().lower() != "native":
        return await asyncio.wait_for(acompletion(**kwargs), timeout=timeout)

    from app.services.llm.adapters import (
        LlmAdapterError,
        build_native_request,
        get_adapter,
        native_unavailable_reason,
        note_fallback,
        resolve_protocol,
        resolve_provider,
        to_litellm_exception,
    )

    reason = native_unavailable_reason(model_config, response_format)
    if reason is not None:
        note_fallback(resolve_provider(model_config), reason)
        return await asyncio.wait_for(acompletion(**kwargs), timeout=timeout)

    protocol = resolve_protocol(model_config)
    adapter = get_adapter(protocol) if protocol else None
    if adapter is None:
        note_fallback(resolve_provider(model_config), "未找到协议实现")
        return await asyncio.wait_for(acompletion(**kwargs), timeout=timeout)

    native_request = build_native_request(
        model_config,
        messages=messages,
        api_key=api_key,
        api_base=api_base,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        timeout=timeout,
    )
    if native_request is None:
        note_fallback(resolve_provider(model_config), "未能构造自有传输层请求")
        return await asyncio.wait_for(acompletion(**kwargs), timeout=timeout)

    try:
        return await asyncio.wait_for(
            adapter.complete(native_request),
            timeout=timeout,
        )
    except LlmAdapterError as exc:
        # 自有错误映射成既有的 litellm 异常类型，让编排层（重试判定、failover、
        # 熔断、内容降级）保持同一套语义，不因传输实现而漂移。
        # llm_provider 取**路由串第一段**（litellm 认的 provider 名），不是
        # 模型表里的 provider 列——后者在本仓库是 "custom"，litellm 那边是
        # "openai"。
        route = str(kwargs.get("model") or "")
        raise to_litellm_exception(
            exc,
            model=kwargs.get("model"),
            provider=route.split("/", 1)[0] or resolve_provider(model_config),
        ) from exc


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
    from app.services.llm.call_trace import LlmTraceBudgetExceeded, current_trace, finish_attempt
    from app.services.llm.provider import _litellm_extra_kwargs
    from app.services.llm_usage import extract_usage, has_complete_usage, record_llm_call_in_new_session

    pool_scope = _pool_scope(model_config, scene)
    rate_limit_started = time.monotonic()
    await _rate_limiter.acquire()
    await _get_token_rate_limiter().acquire(estimate_request_tokens(messages, max_tokens))
    model_limiter = _get_model_rate_limiter(model_config)
    if model_limiter is not None:
        await model_limiter.acquire()
    _pool_metrics.rate_limited(pool_scope, time.monotonic() - rate_limit_started)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # litellm 默认 num_retries=2 会内部重试, 与我们的 tenacity + failover 叠加
        # 导致限流时单条内容烧 8N 次配额。重试策略由 _call_with_retry 统一管理,
        # 这里显式关闭 litellm 内部重试。除非 extra_params 明确覆盖。
        "num_retries": 0,
    }
    kwargs.update(_litellm_extra_kwargs(model_config))
    if current_trace() is not None:
        # A traced physical-attempt cap must include SDK retries. One guarded
        # attempt therefore permits exactly one LiteLLM completion attempt.
        kwargs["num_retries"] = 0
    completion_timeout = _completion_timeout_seconds(kwargs.get("timeout"))
    # 同时传给 LiteLLM 和 asyncio。前者取消底层 HTTP 请求，后者为每个
    # provider 提供一致的兜底截止时间。
    kwargs["timeout"] = completion_timeout
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if response_format:
        kwargs["response_format"] = response_format

    logger.info("LLM call: model=%s, messages=%d", model, len(messages))

    start = time.monotonic()
    attempt = None
    try:
        async with acquire_completion_slot(model_config, scene):
            trace = current_trace()
            if trace is not None:
                attempt = trace.begin_attempt(model_config, model, max_tokens)
            response = await _complete_with_selected_transport(
                kwargs=kwargs,
                messages=messages,
                api_key=api_key,
                api_base=api_base,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
                model_config=model_config,
                timeout=completion_timeout,
            )
        duration_ms = int((time.monotonic() - start) * 1000)
        content = response.choices[0].message.content
        usage = extract_usage(response)
        persisted = await record_llm_call_in_new_session(
            model=model_config,
            request_model=model,
            scene=scene,
            status="DONE",
            duration_ms=duration_ms,
            usage=usage,
            request_id=attempt["request_id"] if attempt else None,
        )
        finish_attempt(
            attempt,
            status="done",
            usage=usage if has_complete_usage(response) else None,
            persisted=persisted,
        )
        # ── 内存指标采集（不阻塞、不重试、失败静默）──
        try:
            from app.core.request_metrics import get_collector
            from app.services.llm_usage import calculate_cost, pricing_from_model

            pricing = pricing_from_model(model_config)
            costs = calculate_cost(
                usage, pricing, provider=model_config.provider if model_config else None, request_model=model
            )
            get_collector().record_llm_call(
                scene=scene,
                status="DONE",
                duration_seconds=duration_ms / 1000,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                cost_usd=costs.total_cost,
            )
        except Exception:
            pass  # 指标采集不能影响主链路
        logger.info("LLM response: %d chars", len(content) if content else 0)
        return content or ""
    except asyncio.CancelledError as exc:
        finish_attempt(attempt, status="cancelled", error=exc)
        raise
    except Exception as exc:
        if isinstance(exc, LlmTraceBudgetExceeded):
            raise
        duration_ms = int((time.monotonic() - start) * 1000)
        persisted = await record_llm_call_in_new_session(
            model=model_config,
            request_model=model,
            scene=scene,
            status="FAILED",
            duration_ms=duration_ms,
            error_message=str(exc),
            request_id=attempt["request_id"] if attempt else None,
        )
        finish_attempt(attempt, status="failed", persisted=persisted, error=exc)
        # ── 失败也记录指标 ──
        try:
            from app.core.request_metrics import get_collector

            get_collector().record_llm_call(
                scene=scene,
                status="FAILED",
                duration_seconds=duration_ms / 1000,
            )
        except Exception:
            pass
        raise


def _should_retry(exc: BaseException) -> bool:
    """tenacity 谓词: 限流错误(含字符串匹配的非 OpenAI 原生 429)不重试。

    RateLimitError 类型 + 字符串检测(429/rate limit/额度)双保险,
    覆盖 DeepSeek/GLM/智谱等通过 openai-compat 抛通用 APIError 的场景。

    BadRequestError (400) 也不重试：内容过滤等确定性错误重试只会浪费时间。
    预算熔断拒绝（LlmBudgetExceededError）同理：窗口未恢复前重试必被再拒。
    """
    from app.services.llm.budget_guard import LlmBudgetExceededError

    if isinstance(exc, RateLimitError | LlmBudgetExceededError) or _is_deterministic_request_error(exc):
        return False
    return not _is_rate_limit_error(exc)


@retry(
    stop=stop_after_attempt(2),
    wait=wait_exponential(multiplier=1, min=2, max=8),
    retry=retry_if_exception(_should_retry),
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
    """Call LLM with a short retry on failure (not rate limit).

    限流错误(类型 + 字符串双检测)不重试：重试只会加重上游限流、烧配额。
    限流错误直接抛出，由 call_llm_with_metadata 的 failover 循环切换到下一个候选模型。
    """
    return await _call_llm_single(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    )
