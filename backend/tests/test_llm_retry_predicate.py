"""LLM provider 重试谓词单测: 验证 RateLimitError 不被重试。

修复前 retry=retry_if_exception_type((Exception,)) 会重试限流错误，
加重上游 429 风暴。修复后 retry_if_not_exception_type((RateLimitError,))
让限流直接 failover 到下一个候选模型。
"""

from __future__ import annotations

import pytest
from litellm import RateLimitError

from app.services.llm.provider import _call_with_retry


@pytest.mark.asyncio
async def test_rate_limit_error_not_retried(monkeypatch):
    """RateLimitError 不重试，立即抛出。"""
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
