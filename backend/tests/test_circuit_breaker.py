"""CircuitBreaker 单测: 状态机 + HALF_OPEN 单探测语义。

重点验证修复: HALF_OPEN 只放行一个探测请求，其余并发请求被拒绝。
"""

from __future__ import annotations

import asyncio

import pytest

from app.services.llm.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
)


@pytest.mark.asyncio
async def test_closed_allows_all():
    """CLOSED 状态放行所有请求。"""
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=1)
    assert await cb.allow_request() is True
    assert await cb.allow_request() is True
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_failures_open_the_breaker():
    """连续失败达阈值后熔断。"""
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        assert await cb.allow_request() is True
        await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert await cb.allow_request() is False


@pytest.mark.asyncio
async def test_success_resets_failure_count():
    """成功重置失败计数，避免偶然失败累积触发误熔断。"""
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    await cb.record_failure()
    await cb.record_failure()
    await cb.record_success()
    assert cb.state == CircuitState.CLOSED
    # 再失败 2 次不应熔断（计数已清零）
    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_half_open_admits_only_one_probe():
    """修复核心: HALF_OPEN 只放行单个探测，其余并发请求被拒绝走 fallback。"""
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)

    # 触发 OPEN
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # 等 cooldown 过期
    await asyncio.sleep(0.06)

    # 第一个请求触发 OPEN→HALF_OPEN 并放行
    first = await cb.allow_request()
    assert first is True
    assert cb.state == CircuitState.HALF_OPEN

    # 后续并发请求应被拒绝（探测在途）
    for _ in range(5):
        assert await cb.allow_request() is False


@pytest.mark.asyncio
async def test_half_open_probe_success_closes_breaker():
    """探测成功 → CLOSED，恢复正常流量。"""
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    await cb.record_failure()
    await asyncio.sleep(0.06)

    await cb.allow_request()  # 进入 HALF_OPEN, 占用探测
    await cb.record_success()

    assert cb.state == CircuitState.CLOSED
    # 恢复后放行所有请求
    assert await cb.allow_request() is True
    assert await cb.allow_request() is True


@pytest.mark.asyncio
async def test_half_open_probe_failure_reopens():
    """探测失败 → 重新 OPEN。"""
    cb = CircuitBreaker(failure_threshold=1, cooldown_seconds=60)
    await cb.record_failure()
    cb._last_failure_time -= 61  # 模拟 cooldown 已过

    await cb.allow_request()  # HALF_OPEN
    await cb.record_failure()

    assert cb.state == CircuitState.OPEN
    assert await cb.allow_request() is False
