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

from litellm import RateLimitError, completion
from litellm.exceptions import BadRequestError  # noqa: I001 — litellm 子模块按 ruff isort 规则应与 litellm 同组
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.services.llm._rate_limit import (
    _get_completion_semaphore,
    _get_model_rate_limiter,
    _rate_limiter,
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
    from app.services.llm.provider import _litellm_extra_kwargs
    from app.services.llm_usage import extract_usage, record_llm_call_in_new_session

    await _rate_limiter.acquire()
    model_limiter = _get_model_rate_limiter(model_config)
    if model_limiter is not None:
        await model_limiter.acquire()

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
        usage = extract_usage(response)
        await record_llm_call_in_new_session(
            model=model_config,
            request_model=model,
            scene=scene,
            status="DONE",
            duration_ms=duration_ms,
            usage=usage,
        )
        # ── 内存指标采集（不阻塞、不重试、失败静默）──
        try:
            from app.core.request_metrics import get_collector
            from app.services.llm_usage import calculate_cost, pricing_from_model

            pricing = pricing_from_model(model_config)
            costs = calculate_cost(usage, pricing, provider=model_config.provider if model_config else None, request_model=model)
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
    """
    if isinstance(exc, RateLimitError | BadRequestError):
        return False
    return not _is_rate_limit_error(exc) and not _is_bad_request_error(exc)


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
