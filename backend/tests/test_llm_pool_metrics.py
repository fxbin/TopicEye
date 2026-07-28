import asyncio
from types import SimpleNamespace

import pytest

from app.services.llm import _rate_limit


def _model(*, model_id: int = 1, channel: str = "official", extra_params=None):
    return SimpleNamespace(
        id=model_id,
        routing_group="analysis",
        channel_name=channel,
        extra_params=extra_params,
    )


@pytest.mark.asyncio
async def test_background_pool_reserves_a_global_slot_for_interactive_scene(monkeypatch):
    """Analysis backfills cannot occupy every global completion worker."""
    monkeypatch.setattr(_rate_limit.settings, "LLM_WORKER_CONCURRENCY", 3)
    _rate_limit.reset_completion_semaphore()
    model = _model()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hold_background_slot():
        async with _rate_limit.acquire_completion_slot(model, "content_analysis"):
            entered.set()
            await release.wait()

    first = asyncio.create_task(hold_background_slot())
    second = asyncio.create_task(hold_background_slot())
    await entered.wait()
    # Let both background coroutines acquire the shared two-slot budget.
    await asyncio.sleep(0)

    async with _rate_limit.acquire_completion_slot(model, "daily_report"):
        metrics = _rate_limit.get_llm_pool_metrics()
        assert metrics["route:analysis|channel:official|scene:daily_report"]["active"] == 1
        assert metrics["route:analysis|channel:official|scene:content_analysis"]["max_active"] == 2

    release.set()
    await asyncio.gather(first, second)
    _rate_limit.reset_completion_semaphore()


@pytest.mark.asyncio
async def test_pool_configuration_caps_one_channel_and_exposes_queue_wait(monkeypatch):
    monkeypatch.setattr(_rate_limit.settings, "LLM_WORKER_CONCURRENCY", 4)
    _rate_limit.reset_completion_semaphore()
    model = _model(extra_params={"pool": {"max_concurrency": 1}})
    first_entered = asyncio.Event()
    release = asyncio.Event()
    second_entered = asyncio.Event()

    async def first():
        async with _rate_limit.acquire_completion_slot(model, "daily_report"):
            first_entered.set()
            await release.wait()

    async def second():
        async with _rate_limit.acquire_completion_slot(model, "daily_report"):
            second_entered.set()

    first_task = asyncio.create_task(first())
    await first_entered.wait()
    second_task = asyncio.create_task(second())
    await asyncio.sleep(0.01)
    assert not second_entered.is_set()

    release.set()
    await asyncio.gather(first_task, second_task)
    metrics = _rate_limit.get_llm_pool_metrics()
    scope = "route:analysis|channel:official|scene:daily_report"
    assert metrics[scope]["max_active"] == 1
    assert metrics[scope]["queue_wait_seconds"] > 0
    _rate_limit.reset_completion_semaphore()


def test_pool_scope_uses_channel_and_scene_not_prompt_data():
    model = _model(channel="openrouter")
    assert _rate_limit._pool_scope(model, "content_analysis") == (
        "route:analysis|channel:openrouter|scene:content_analysis"
    )
