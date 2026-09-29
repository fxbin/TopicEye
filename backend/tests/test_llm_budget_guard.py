"""LLM 预算熔断闸（budget_guard）的行为回归测试。

覆盖三窗语义：
- 超限拒绝（分钟/日窗各自生效），拒绝事件可观测（budget_rejected 事件 + warning）；
- 三窗全 0 时零开销直通（不触发计数查询）；
- 计数查询失败 fail-open（保险丝自身故障不阻断主链路）；
- provider 集成：预算拒绝不进入 failover/真实调用、不污染路由熔断器、
  响应缓存命中（免费）在预算耗尽时仍放行。
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.llm import provider
from app.services.llm._call_engine import _should_retry
from app.services.llm.budget_guard import (
    LlmBudgetExceededError,
    _budget_limits,
    ensure_llm_budget,
)
from app.services.llm.circuit_breaker import (
    get_llm_circuit_breaker,
    reset_llm_circuit_breakers,
)
from app.services.llm.response_cache import get_llm_cache


def _set_budget(monkeypatch, minute: int, hour: int, day: int) -> None:
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_MINUTE", minute)
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_HOUR", hour)
    monkeypatch.setattr(settings, "LLM_BUDGET_CALLS_PER_DAY", day)


@pytest.fixture(autouse=True)
def _isolate_route_state():
    provider._failover.reset()
    reset_llm_circuit_breakers()
    get_llm_cache().clear()
    yield
    provider._failover.reset()
    reset_llm_circuit_breakers()
    get_llm_cache().clear()


@pytest.mark.asyncio
async def test_all_zero_budget_skips_count_query(monkeypatch):
    """三窗全 0 = 预算闸关闭：不应触碰计数查询。"""
    _set_budget(monkeypatch, 0, 0, 0)
    assert _budget_limits() is None

    async def _boom():
        raise AssertionError("budget disabled must not query call counts")

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _boom)
    await ensure_llm_budget(scene="test")


@pytest.mark.asyncio
async def test_minute_window_rejects_and_emits_event(monkeypatch):
    _set_budget(monkeypatch, minute=2, hour=0, day=0)

    async def _counts():
        return 2, 5, 10  # 分钟窗已到 2/2

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)
    events: list[tuple] = []
    monkeypatch.setattr(
        "app.services.llm.budget_guard.record_llm_pool_circuit_event",
        lambda *args: events.append(args),
    )
    audits: list[dict] = []

    async def _fake_audit(**kwargs):
        audits.append(kwargs)

    monkeypatch.setattr("app.services.llm.budget_guard._record_budget_rejection", _fake_audit)

    with pytest.raises(LlmBudgetExceededError, match="minute"):
        await ensure_llm_budget(scene="analysis")
    assert events and events[0][2] == "budget_rejected"
    assert audits and audits[0]["scene"] == "analysis"
    assert "minute window: 2/2" in audits[0]["detail"]


@pytest.mark.asyncio
async def test_day_window_rejects(monkeypatch):
    _set_budget(monkeypatch, minute=0, hour=0, day=100)

    async def _counts():
        return 1, 50, 100  # 日窗已到 100/100

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)

    async def _fake_audit(**kwargs):
        return None

    monkeypatch.setattr("app.services.llm.budget_guard._record_budget_rejection", _fake_audit)
    with pytest.raises(LlmBudgetExceededError, match="day"):
        await ensure_llm_budget(scene="analysis")


@pytest.mark.asyncio
async def test_hour_window_rejects(monkeypatch):
    _set_budget(monkeypatch, minute=0, hour=500, day=0)

    async def _counts():
        return 10, 500, 600  # 小时窗已到 500/500

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)

    async def _fake_audit(**kwargs):
        return None

    monkeypatch.setattr("app.services.llm.budget_guard._record_budget_rejection", _fake_audit)
    with pytest.raises(LlmBudgetExceededError, match="hour"):
        await ensure_llm_budget(scene="analysis")


@pytest.mark.asyncio
async def test_within_budget_passes(monkeypatch):
    _set_budget(monkeypatch, minute=10, hour=100, day=1000)

    async def _counts():
        return 3, 40, 500

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)
    await ensure_llm_budget(scene="analysis")  # 不抛即通过


@pytest.mark.asyncio
async def test_count_query_failure_fails_open(monkeypatch, caplog):
    _set_budget(monkeypatch, minute=10, hour=100, day=1000)

    async def _boom():
        raise RuntimeError("db unavailable")

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _boom)
    with caplog.at_level("WARNING"):
        await ensure_llm_budget(scene="analysis")  # fail-open，不抛
    assert any("budget check skipped" in rec.message for rec in caplog.records)


def test_should_retry_rejects_budget_error():
    assert _should_retry(LlmBudgetExceededError("minute window")) is False


@pytest.mark.asyncio
async def test_provider_rejects_before_failover_and_keeps_breaker_clean(monkeypatch):
    """预算拒绝：不进入真实调用/failover，也不计入路由熔断器失败。"""
    _set_budget(monkeypatch, minute=1, hour=0, day=0)

    async def _counts():
        return 1, 0, 0

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)

    async def _forbidden(*args, **kwargs):
        raise AssertionError("budget-exceeded call must not reach the failover layer")

    monkeypatch.setattr(provider, "_call_llm_with_metadata_inner", _forbidden)

    breaker = get_llm_circuit_breaker("budget_test")
    failures_before = breaker.status()["failure_count"]

    with pytest.raises(LlmBudgetExceededError):
        await provider.call_llm_with_metadata(
            [{"role": "user", "content": "预算耗尽时的调用"}],
            routing_group="budget_test",
            scene="test",
        )
    assert breaker.status()["failure_count"] == failures_before, "预算拒绝不是故障，不得污染熔断器"


@pytest.mark.asyncio
async def test_cache_hit_still_served_when_budget_exhausted(monkeypatch):
    """预算耗尽时缓存命中（免费）必须继续放行。"""
    _set_budget(monkeypatch, minute=100, hour=0, day=0)

    async def _inner(messages, temperature, max_tokens, scene, routing_group, response_format=None):
        return "cached-answer", {"model": "m1"}

    async def _zero_counts():
        return 0, 0, 0

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _zero_counts)
    monkeypatch.setattr(provider, "_call_llm_with_metadata_inner", _inner)

    messages = [{"role": "user", "content": "会被缓存的问题"}]
    text, meta = await provider.call_llm_with_metadata(messages, routing_group="budget_cache", scene="test")
    assert text == "cached-answer"
    assert meta.get("cache_hit") is not True

    # 预算降到已耗尽，同参调用必须仍能从缓存拿到答案
    _set_budget(monkeypatch, minute=1, hour=0, day=0)

    async def _counts():
        return 1, 0, 0

    monkeypatch.setattr("app.services.llm_usage.count_recent_llm_calls", _counts)

    text2, meta2 = await provider.call_llm_with_metadata(messages, routing_group="budget_cache", scene="test")
    assert text2 == "cached-answer"
    assert meta2.get("cache_hit") is True
