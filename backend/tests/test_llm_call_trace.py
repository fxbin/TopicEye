"""Trace/cap tests use a mocked transport and real isolated usage rows."""

import asyncio
import os
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models.llm_model import LlmCallLog
from app.services.llm import _call_engine as engine, provider
from app.services.llm.call_trace import LlmTraceBudgetExceeded, llm_call_budget, trace_llm_call
from app.services.llm.circuit_breaker import reset_llm_circuit_breakers
from app.services.llm.response_cache import LLMCache


def model(identifier=1):
    return SimpleNamespace(
        id=identifier,
        name=f"Mock {identifier}",
        model_id=f"mock-{identifier}",
        provider="openai",
        api_key=None,
        api_base="https://mock.invalid/v1",
        enabled=True,
        routing_group="trace-test",
        routing_priority=identifier,
        cooldown_seconds=60,
        temperature=0,
        max_tokens=100,
        context_window=1000,
        requests_per_minute=1000,
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.002,
        extra_params={"pricing_currency": "USD", "litellm_params": {"num_retries": 4}},
    )


def response():
    return SimpleNamespace(
        model="provider-reported-mock-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content='{"ok":true}'))],
        usage=SimpleNamespace(prompt_tokens=20, completion_tokens=5, total_tokens=25),
    )


@pytest_asyncio.fixture
async def trace_runtime(monkeypatch):
    pg = create_async_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    sessions = async_sessionmaker(pg, expire_on_commit=False)
    monkeypatch.setattr("app.core.database.async_session", sessions)
    monkeypatch.setattr("app.services.llm.budget_guard.ensure_llm_budget", AsyncMock())
    monkeypatch.setattr(engine._rate_limiter, "acquire", AsyncMock())
    monkeypatch.setattr(engine, "_get_token_rate_limiter", lambda: SimpleNamespace(acquire=AsyncMock()))
    monkeypatch.setattr(engine, "_get_model_rate_limiter", lambda _model: None)

    @asynccontextmanager
    async def slot(*args):
        yield

    monkeypatch.setattr(engine, "acquire_completion_slot", slot)
    cache = LLMCache()
    monkeypatch.setattr("app.services.llm.response_cache.get_llm_cache", lambda: cache)
    reset_llm_circuit_breakers()
    provider._failover.reset()
    models = [model(1), model(2)]
    monkeypatch.setattr(provider._model_cache, "get_route_models", AsyncMock(return_value=models))
    yield sessions, models
    await pg.dispose()


@pytest.mark.asyncio
async def test_failover_attempts_link_to_real_rows_without_pricing_failed_usage_as_free(trace_runtime, monkeypatch):
    sessions, _ = trace_runtime
    complete = AsyncMock(side_effect=[RuntimeError("429 rate limit"), response()])
    monkeypatch.setattr(engine, "acompletion", complete)
    with (
        llm_call_budget(max_physical_attempts=2, max_cost_usd=0.01),
        trace_llm_call("event_eval:mock-run:query:1") as trace,
    ):
        await provider.call_llm_with_metadata(
            [{"role": "user", "content": "mock"}], routing_group="trace-test", max_tokens=100
        )
        result = trace.report()
    assert complete.await_count == 2
    assert all(call.kwargs["num_retries"] == 0 for call in complete.await_args_list)
    assert [attempt["status"] for attempt in result["physical_attempts"]] == ["failed", "done"]
    assert result["cost_usd"] is None and result["usage_linkage_verified"] is False
    assert result["route"]["provider_reported_model"] == "provider-reported-mock-model"
    async with sessions() as db:
        logs = (await db.scalars(select(LlmCallLog).order_by(LlmCallLog.id))).all()
        assert [log.request_id for log in logs] == [attempt["request_id"] for attempt in result["physical_attempts"]]
        assert logs[-1].input_tokens == 20 and logs[-1].output_tokens == 5
        assert logs[-1].actual_model == "provider-reported-mock-model"


@pytest.mark.asyncio
async def test_physical_cap_survives_failover_and_does_not_mark_next_model_unhealthy(trace_runtime, monkeypatch):
    _, models = trace_runtime
    complete = AsyncMock(side_effect=RuntimeError("429 rate limit"))
    monkeypatch.setattr(engine, "acompletion", complete)
    with (
        llm_call_budget(max_physical_attempts=1, max_cost_usd=0.01),
        trace_llm_call("event_eval:physical-cap") as trace,
    ):
        with pytest.raises(LlmTraceBudgetExceeded, match="physical"):
            await provider.call_llm_with_metadata(
                [{"role": "user", "content": "mock"}], routing_group="trace-test", max_tokens=100
            )
        assert len(trace.attempts) == 1
    assert complete.await_count == 1
    assert not provider._failover.should_skip(provider._model_key(models[1]))


@pytest.mark.asyncio
async def test_cost_cap_refuses_unknown_prices_before_transport(trace_runtime, monkeypatch):
    _, models = trace_runtime
    models[0].cost_per_1k_input = models[0].cost_per_1k_output = None
    complete = AsyncMock(return_value=response())
    monkeypatch.setattr(engine, "acompletion", complete)
    with (
        llm_call_budget(max_physical_attempts=2, max_cost_usd=0.01),
        trace_llm_call("event_eval:unknown-price") as trace,
    ):
        with pytest.raises(LlmTraceBudgetExceeded, match="known unit prices"):
            await provider.call_llm_with_metadata(
                [{"role": "user", "content": "mock"}], routing_group="trace-test", max_tokens=100
            )
        assert trace.attempts == []
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_cache_provenance_keeps_original_identity_without_charging_twice(trace_runtime, monkeypatch):
    complete = AsyncMock(return_value=response())
    monkeypatch.setattr(engine, "acompletion", complete)
    messages = [{"role": "user", "content": "same mock request"}]
    with llm_call_budget(max_physical_attempts=1, max_cost_usd=0.01):
        with trace_llm_call("event_eval:cache-producer") as first:
            await provider.call_llm_with_metadata(messages, routing_group="trace-test", max_tokens=100)
        with trace_llm_call("event_eval:cache-consumer") as second:
            await provider.call_llm_with_metadata(messages, routing_group="trace-test", max_tokens=100)
            result = second.report()
    assert complete.await_count == 1
    assert result["cache_hit"] and result["physical_attempts"] == [] and result["cost_usd"] == 0
    assert result["route"]["origin_request_id"] == first.attempts[0]["request_id"]
    assert result["route"]["provider_reported_model"] == "provider-reported-mock-model"


@pytest.mark.asyncio
async def test_concurrent_logical_requests_keep_separate_attempt_ids(trace_runtime, monkeypatch):
    monkeypatch.setattr(engine, "acompletion", AsyncMock(return_value=response()))

    async def request(number):
        with trace_llm_call(f"event_eval:parallel:{number}") as trace:
            await provider.call_llm_with_metadata(
                [{"role": "user", "content": f"mock {number}"}], routing_group="trace-test", max_tokens=100
            )
            return trace.report()

    with llm_call_budget(max_physical_attempts=2, max_cost_usd=0.01):
        first, second = await asyncio.gather(request(1), request(2))
    assert first["logical_request_id"] != second["logical_request_id"]
    assert len(first["physical_attempts"]) == len(second["physical_attempts"]) == 1
    assert first["physical_attempts"][0]["request_id"] != second["physical_attempts"][0]["request_id"]


@pytest.mark.asyncio
async def test_unknown_currency_is_refused_and_legacy_cache_is_not_usage_proof(trace_runtime, monkeypatch):
    _, models = trace_runtime
    models[0].extra_params.pop("pricing_currency")
    complete = AsyncMock(return_value=response())
    monkeypatch.setattr(engine, "acompletion", complete)
    with llm_call_budget(max_physical_attempts=1, max_cost_usd=0.01), trace_llm_call() as trace:
        with pytest.raises(LlmTraceBudgetExceeded, match="USD pricing"):
            await provider.call_llm_with_metadata(
                [{"role": "user", "content": "mock"}], routing_group="trace-test", max_tokens=100
            )
        assert trace.attempts == []
    complete.assert_not_awaited()
    with trace_llm_call() as cached:
        cached.route = {"cache_hit": True}
        assert not cached.report()["usage_linkage_verified"]
        assert cached.report()["cost_usd"] is None


@pytest.mark.asyncio
async def test_free_model_name_without_explicit_prices_cannot_bypass_budget(trace_runtime, monkeypatch):
    _, models = trace_runtime
    models[0].model_id = "proxy/deepseek-v4-flash-free"
    models[0].cost_per_1k_input = models[0].cost_per_1k_output = None
    models[0].extra_params = {}
    complete = AsyncMock(return_value=response())
    monkeypatch.setattr(engine, "acompletion", complete)
    with llm_call_budget(max_physical_attempts=1, max_cost_usd=0.01), trace_llm_call() as trace:
        with pytest.raises(LlmTraceBudgetExceeded, match="explicit known unit prices"):
            await provider.call_llm_with_metadata(
                [{"role": "user", "content": "mock"}], routing_group="trace-test", max_tokens=100
            )
        assert trace.attempts == []
    complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonzero_cache_price_is_not_currency_free_even_with_zero_base_rates(trace_runtime):
    from app.services.llm_usage import TokenUsage, record_llm_call_in_new_session

    _, models = trace_runtime
    configured = models[0]
    configured.cost_per_1k_input = configured.cost_per_1k_output = 0
    configured.extra_params = {"cost_per_1m_input_cache_hit": 2.0}
    evidence = await record_llm_call_in_new_session(
        model=configured,
        request_model=configured.model_id,
        scene="trace-test",
        status="DONE",
        usage=TokenUsage(input_tokens=20, output_tokens=2, cache_read_tokens=10, actual_model="reported-model"),
    )
    assert evidence["total_cost"] > 0 and evidence["pricing_currency"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("usage", [{}, {"prompt_tokens": 20}, {"prompt_tokens": "20", "completion_tokens": 1}])
async def test_missing_or_invalid_token_counters_do_not_become_known_zero_usage(trace_runtime, monkeypatch, usage):
    received = response()
    received.usage = usage
    monkeypatch.setattr(engine, "acompletion", AsyncMock(return_value=received))
    with llm_call_budget(max_physical_attempts=1, max_cost_usd=0.01), trace_llm_call() as trace:
        await provider.call_llm_with_metadata(
            [{"role": "user", "content": "mock unknown usage"}], routing_group="trace-test", max_tokens=100
        )
    result = trace.report()
    assert result["physical_attempts"][0]["persisted"]
    assert result["physical_attempts"][0]["usage"] is None
    assert not result["usage_linkage_verified"] and result["cost_usd"] is None
    assert not result["route"]["origin_usage_linkage_verified"]


@pytest.mark.parametrize(
    "usage", [{"input_tokens": 20, "output_tokens": 1}, {"promptTokenCount": 20, "candidatesTokenCount": 1}]
)
def test_explicit_anthropic_and_gemini_counter_aliases_are_supported(usage):
    from app.services.llm_usage import has_complete_usage

    assert has_complete_usage({"usage": usage})
