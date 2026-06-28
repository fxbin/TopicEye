"""LLM provider 重试谓词单测: 验证限流错误(类型 + 字符串)不被重试。

修复前 retry_if_not_exception_type((RateLimitError,)) 只排除 RateLimitError 类型,
非 OpenAI 原生 provider (DeepSeek/GLM/智谱) 的 429 抛通用 APIError, 消息含 "429",
仍被重试。修复后用 _should_retry 字符串+类型双检测。
"""

from __future__ import annotations

import pytest
from litellm import RateLimitError

from app.services.llm.provider import _call_with_retry, _should_retry


@pytest.mark.asyncio
async def test_rate_limit_error_not_retried(monkeypatch):
    """RateLimitError 类型不重试，立即抛出。"""
    call_count = 0

    async def fake_single_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RateLimitError(
            message="Rate limited",
            model="test-model",
            llm_provider="openai",
        )

    monkeypatch.setattr(
        "app.services.llm.provider._call_llm_single", fake_single_call
    )

    with pytest.raises(RateLimitError):
        await _call_with_retry(
            messages=[],
            model="test-model",
            api_key="k",
            api_base=None,
            temperature=0.3,
            max_tokens=100,
            response_format=None,
        )

    # 核心断言：限流错误只调用一次，没有重试
    assert call_count == 1, f"RateLimitError should NOT retry, but called {call_count} times"


@pytest.mark.asyncio
async def test_string_429_error_not_retried(monkeypatch):
    """非 OpenAI 原生 provider 的字符串 429 (APIError/RuntimeError) 也不重试。"""
    call_count = 0

    async def fake_single_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        # 模拟 DeepSeek/GLM 通过 openai-compat 抛的通用错误, 消息含 429 但非 RateLimitError 类型
        raise RuntimeError("Error code: 429 - {'error': {'message': '请求过于频繁'}}")

    monkeypatch.setattr(
        "app.services.llm.provider._call_llm_single", fake_single_call
    )

    with pytest.raises(RuntimeError):
        await _call_with_retry(
            messages=[],
            model="test-model",
            api_key="k",
            api_base=None,
            temperature=0.3,
            max_tokens=100,
            response_format=None,
        )

    assert call_count == 1, f"string-429 should NOT retry, but called {call_count} times"


def test_should_retry_predicate():
    """谓词函数单元测试: 限流(类型+字符串)不重试, 其他重试。"""
    # RateLimitError 类型
    assert _should_retry(RateLimitError("429", model="m", llm_provider="openai")) is False
    # 字符串 429 (非类型)
    assert _should_retry(RuntimeError("Error 429 rate limit")) is False
    assert _should_retry(RuntimeError("请求过于频繁")) is False
    assert _should_retry(RuntimeError("quota exceeded")) is False
    # 非限流错误应重试
    assert _should_retry(ConnectionError("timeout")) is True
    assert _should_retry(ValueError("bad json")) is True


@pytest.mark.asyncio
async def test_transient_error_is_retried(monkeypatch):
    """非限流的瞬时错误（如网络超时）仍会重试一次。"""
    call_count = 0

    async def fake_single_call(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise ConnectionError("transient")
        return "ok"

    monkeypatch.setattr(
        "app.services.llm.provider._call_llm_single", fake_single_call
    )

    result = await _call_with_retry(
        messages=[],
        model="test-model",
        api_key="k",
        api_base=None,
        temperature=0.3,
        max_tokens=100,
        response_format=None,
    )

    assert result == "ok"
    assert call_count == 2  # 第一次失败 + 第二次成功
