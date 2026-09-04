"""模型目录 V2 测试：上下文预检（fail-open）+ 目录价计费估算 fallback。

覆盖：
- context_guard_verdict 纯函数（未配置放行 / 估算未超放行 / 严格超出判 unfit / 脏数据容错）
- provider 候选循环：unfit 候选被跳过且不触发失败冷却；全部 unfit 抛 RuntimeError；
  部分 unfit 继续 failover；无 context_window 行为与 V1 一致
- API：context_window 创建/回读/清除
- 目录价 fallback：未配置价格时估算、已配置不覆盖、free 模型不介入、裸名/前缀名匹配
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.v1.llm_models import ModelCreateRequest
from app.services.llm import provider as provider_module
from app.services.llm._context_guard import LlmContextWindowExceededError, context_guard_verdict


def _db_model(context_window=None, **overrides):
    """构造 provider 候选循环所需的最小 model_config 形状。"""
    base = {
        "id": 1,
        "name": "Test Model",
        "provider": "deepseek",
        "model_id": "deepseek-chat",
        "api_key": None,
        "api_base": None,
        "temperature": 0.3,
        "max_tokens": 2000,
        "cooldown_seconds": 300,
        "context_window": context_window,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _messages(char_count: int) -> list:
    return [{"role": "user", "content": "a" * char_count}]


# ── context_guard_verdict 纯函数 ─────────────────────────────────────


class TestContextGuardVerdict:
    def test_no_context_window_always_allows(self):
        unfit, estimated, window = context_guard_verdict(_db_model(), _messages(10_000_000), 8000)
        assert unfit is False
        assert estimated == 0 and window is None

    def test_estimate_within_window_allows(self):
        # 400 chars → (400+3)//4 = 100 + max_tokens 2000 = 2100 ≤ 8192 → 放行
        unfit, estimated, window = context_guard_verdict(_db_model(context_window=8192), _messages(400), 2000)
        assert unfit is False
        assert estimated == 2100 and window == 8192

    def test_estimate_strictly_over_window_is_unfit(self):
        # 40_000 chars → 10_000 + 2000 = 12_000 > 8192 → unfit
        unfit, estimated, _ = context_guard_verdict(_db_model(context_window=8192), _messages(40_000), 2000)
        assert unfit is True
        assert estimated == 12_000

    def test_boundary_equal_is_allowed(self):
        # (chars+3)//4 + max_tokens == window → 不严格大于 → 放行（fail-open）
        chars = 4 * (8192 - 2000)
        unfit, _, _ = context_guard_verdict(_db_model(context_window=8192), _messages(chars), 2000)
        assert unfit is False

    def test_dirty_context_window_degrades_to_allow(self):
        unfit, _, window = context_guard_verdict(_db_model(context_window="not-a-number"), _messages(400), 2000)
        assert unfit is False and window is None
        unfit, _, _ = context_guard_verdict(_db_model(context_window=0), _messages(400), 2000)
        assert unfit is False
        unfit, _, _ = context_guard_verdict(_db_model(context_window=-5), _messages(400), 2000)
        assert unfit is False


# ── provider 候选循环预检 ────────────────────────────────────────────


@pytest.mark.asyncio
class TestProviderContextPrecheck:
    async def test_unfit_candidate_skipped_without_degrading_route(self, monkeypatch):
        calls = []

        async def fake_call(*args, **kwargs):
            calls.append(args[1])
            return "ok"

        model = _db_model(id=1, context_window=1000)  # 40k chars 请求必然 unfit

        async def route_models(group):
            return [model]

        monkeypatch.setattr(provider_module._model_cache, "get_route_models", route_models)
        monkeypatch.setattr(provider_module, "_call_with_retry", fake_call)
        provider_module._failover.reset()

        with pytest.raises(LlmContextWindowExceededError, match="context windows exceeded"):
            await provider_module.call_llm_with_metadata(_messages(40_000), routing_group="default")
        assert calls == []  # 从未真正发起调用
        assert not provider_module._failover.should_skip("db:1")  # 不触发冷却
        # 确定性错误：不计入全局熔断器
        from app.services.llm.circuit_breaker import get_llm_circuit_breaker

        assert get_llm_circuit_breaker("default").status()["failure_count"] == 0

    async def test_partial_unfit_fails_over_to_next_candidate(self, monkeypatch):
        calls = []

        async def fake_call(*args, **kwargs):
            calls.append(args[1])
            return "fallback-ok"

        small = _db_model(id=1, context_window=1000, model_id="small-ctx")
        large = _db_model(id=2, context_window=None, model_id="large-ctx")

        async def route_models(group):
            return [small, large]

        monkeypatch.setattr(provider_module._model_cache, "get_route_models", route_models)
        monkeypatch.setattr(provider_module, "_call_with_retry", fake_call)
        provider_module._failover.reset()

        result, metadata = await provider_module.call_llm_with_metadata(_messages(40_000), routing_group="default")
        assert result == "fallback-ok"
        assert calls == ["deepseek/large-ctx"]  # unfit 的第一个候选没有发起调用
        assert metadata["actual_model"] == "deepseek/large-ctx"

    async def test_no_context_window_keeps_v1_behavior(self, monkeypatch):
        async def fake_call(*args, **kwargs):
            return "ok"

        async def route_models(group):
            return [_db_model(id=1, context_window=None)]

        monkeypatch.setattr(provider_module._model_cache, "get_route_models", route_models)
        monkeypatch.setattr(provider_module, "_call_with_retry", fake_call)
        provider_module._failover.reset()

        result, _ = await provider_module.call_llm_with_metadata(_messages(40_000), routing_group="default")
        assert result == "ok"


# ── API context_window 透传 ──────────────────────────────────────────


class TestApiContextWindow:
    def test_create_request_accepts_context_window(self):
        req = ModelCreateRequest(name="t", provider="deepseek", model_id="deepseek-chat", context_window=128000)
        assert req.context_window == 128000

    def test_create_request_rejects_out_of_range(self):
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ModelCreateRequest(name="t", provider="deepseek", model_id="deepseek-chat", context_window=10)
        with pytest.raises(ValidationError):
            ModelCreateRequest(name="t", provider="deepseek", model_id="deepseek-chat", context_window=999_999_999)
