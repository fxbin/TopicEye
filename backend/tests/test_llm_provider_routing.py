from types import SimpleNamespace
import asyncio

import pytest

from app.services.llm import provider
from app.services.llm import _call_engine
from app.services.llm import _rate_limit


def _model(model_id: int, name: str, priority: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=model_id,
        name=name,
        provider="openai",
        model_id=name,
        api_key="test-key",
        api_base="https://example.test/v1",
        routing_group="default",
        routing_priority=priority,
        cooldown_seconds=300,
        temperature=0.3,
        max_tokens=2000,
        requests_per_minute=60,
        extra_params=None,
    )


@pytest.mark.asyncio
async def test_call_llm_fails_over_across_ordered_model_chain(monkeypatch):
    provider._failover.reset()
    models = [_model(1, "first", 10), _model(2, "second", 20)]
    calls = []

    async def route_models(group="default", user_id=None):
        return models

    async def fake_call(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    ):
        calls.append(model)
        if model == "openai/first":
            raise RuntimeError("first failed")
        return "ok from second"

    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)
    monkeypatch.setattr(provider, "_call_with_retry", fake_call)

    result = await provider.call_llm([{"role": "user", "content": "hello"}])

    assert result == "ok from second"
    assert calls == ["openai/first", "openai/second"]


@pytest.mark.asyncio
async def test_call_llm_skips_cooling_down_candidate(monkeypatch):
    provider._failover.reset()
    models = [_model(1, "first", 10), _model(2, "second", 20)]
    calls = []

    async def route_models(group="default", user_id=None):
        return models

    async def fake_call(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    ):
        calls.append(model)
        return f"ok from {model}"

    provider._failover.on_failure("db:1", cooldown_seconds=300)
    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)
    monkeypatch.setattr(provider, "_call_with_retry", fake_call)

    result = await provider.call_llm([{"role": "user", "content": "hello"}])

    assert result == "ok from openai/second"
    assert calls == ["openai/second"]


@pytest.mark.asyncio
async def test_call_llm_with_metadata_returns_selected_model(monkeypatch):
    provider._failover.reset()
    models = [_model(1, "lite", 10)]

    async def route_models(group="default", user_id=None):
        return models

    async def fake_call(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    ):
        return "{}"

    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)
    monkeypatch.setattr(provider, "_call_with_retry", fake_call)

    result, metadata = await provider.call_llm_with_metadata(
        [{"role": "user", "content": "hello"}],
        routing_group="analysis_lite",
    )

    assert result == "{}"
    assert metadata["actual_model"] == "openai/lite"
    assert metadata["routing_group"] == "analysis_lite"
    assert metadata["model_id"] == 1


@pytest.mark.asyncio
async def test_call_llm_uses_requested_routing_group(monkeypatch):
    provider._failover.reset()
    models = [_model(1, "lite", 10)]
    observed = {}

    async def route_models(group="default", user_id=None):
        observed["group"] = group
        observed["user_id"] = user_id
        return models

    async def fake_call(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    ):
        return f"ok from {model}"

    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)
    monkeypatch.setattr(provider, "_call_with_retry", fake_call)

    result = await provider.call_llm(
        [{"role": "user", "content": "hello"}],
        user_id=42,
        routing_group="analysis_lite",
    )

    assert result == "ok from openai/lite"
    assert observed == {"group": "analysis_lite", "user_id": 42}


@pytest.mark.asyncio
async def test_call_llm_requires_enabled_db_route_models(monkeypatch):
    provider._failover.reset()

    async def route_models(group="default", user_id=None):
        return []

    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)

    with pytest.raises(RuntimeError, match="No enabled LLM route models configured"):
        await provider.call_llm([{"role": "user", "content": "hello"}])


@pytest.mark.asyncio
async def test_call_llm_passes_user_id_to_route_model_cache(monkeypatch):
    provider._failover.reset()
    models = [_model(1, "personal", 10)]
    observed = {}

    async def route_models(group="default", user_id=None):
        observed["group"] = group
        observed["user_id"] = user_id
        return models

    async def fake_call(
        messages, model, api_key, api_base, temperature, max_tokens, response_format, model_config, scene
    ):
        return f"ok from {model}"

    monkeypatch.setattr(provider._model_cache, "get_route_models", route_models)
    monkeypatch.setattr(provider, "_call_with_retry", fake_call)

    result = await provider.call_llm([{"role": "user", "content": "hello"}], user_id=42)

    assert result == "ok from openai/personal"
    assert observed == {"group": "default", "user_id": 42}


@pytest.mark.asyncio
async def test_llm_completion_calls_are_globally_bounded(monkeypatch):
    provider.reset_completion_semaphore()
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    class FakeMessage:
        content = "{}"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    async def fake_to_thread(func, **kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        return FakeResponse()

    async def fake_record_llm_call_in_new_session(**kwargs):
        return None

    monkeypatch.setattr(_rate_limit.settings, "LLM_WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(_call_engine.asyncio, "to_thread", fake_to_thread)
    # _call_llm_single 内部延迟 import record_llm_call_in_new_session，patch 其来源模块
    import app.services.llm_usage as llm_usage_mod
    monkeypatch.setattr(llm_usage_mod, "record_llm_call_in_new_session", fake_record_llm_call_in_new_session)

    try:
        await asyncio.gather(
            *[
                _call_engine._call_llm_single(
                    [{"role": "user", "content": f"hello {index}"}],
                    "openai/test",
                    "test-key",
                    "https://example.test/v1",
                    0.2,
                    100,
                    None,
                    None,
                    "test",
                )
                for index in range(5)
            ]
        )

        assert max_active == 2
    finally:
        provider.reset_completion_semaphore()


@pytest.mark.asyncio
async def test_llm_completion_calls_are_bounded_per_model(monkeypatch):
    provider.reset_completion_semaphore()
    provider.reset_model_rate_limiters()
    active = 0
    max_active = 0
    lock = asyncio.Lock()
    model_config = _model(99, "limited", 10)
    model_config.requests_per_minute = 1

    class FastRateLimiter(_rate_limit.RateLimiter):
        def __init__(self, max_requests: int = 60, window_seconds: int = 60):
            super().__init__(max_requests=max_requests, window_seconds=0.03)

    class FakeMessage:
        content = "{}"

    class FakeChoice:
        message = FakeMessage()

    class FakeResponse:
        choices = [FakeChoice()]

    async def fake_to_thread(func, **kwargs):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.02)
        async with lock:
            active -= 1
        return FakeResponse()

    async def fake_record_llm_call_in_new_session(**kwargs):
        return None

    monkeypatch.setattr(_rate_limit, "RateLimiter", FastRateLimiter)
    monkeypatch.setattr(_rate_limit.settings, "LLM_WORKER_CONCURRENCY", 5)
    monkeypatch.setattr(_call_engine.asyncio, "to_thread", fake_to_thread)
    import app.services.llm_usage as llm_usage_mod
    monkeypatch.setattr(llm_usage_mod, "record_llm_call_in_new_session", fake_record_llm_call_in_new_session)

    try:
        await asyncio.gather(
            *[
                _call_engine._call_llm_single(
                    [{"role": "user", "content": f"hello {index}"}],
                    "openai/limited",
                    "test-key",
                    "https://example.test/v1",
                    0.2,
                    100,
                    None,
                    model_config,
                    "test",
                )
                for index in range(3)
            ]
        )

        assert max_active == 1
    finally:
        provider.reset_completion_semaphore()
        provider.reset_model_rate_limiters()
