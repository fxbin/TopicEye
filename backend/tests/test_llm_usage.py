from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.core.database import Base
from app.models.llm_model import LlmCallLog
from app.services.llm_usage import (
    TokenUsage,
    calculate_cost,
    extract_usage,
    pricing_from_model,
    record_llm_call,
    record_llm_call_in_new_session,
)


def test_extract_usage_reads_openai_cache_tokens():
    response = SimpleNamespace(
        model="deepseek-chat",
        usage=SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=500,
            prompt_tokens_details={"cached_tokens": 200},
        ),
    )

    usage = extract_usage(response)

    assert usage.input_tokens == 1000
    assert usage.output_tokens == 500
    assert usage.cache_read_tokens == 200
    assert usage.actual_model == "deepseek-chat"


def test_calculate_cost_uses_per_million_pricing_and_cache_hit_discount():
    usage = extract_usage(
        {
            "model": "deepseek-chat",
            "usage": {
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "prompt_tokens_details": {"cached_tokens": 200},
            },
        }
    )

    cost = calculate_cost(
        usage,
        {"input": 1.0, "output": 2.0, "cache_hit": 0.02, "cache_create": None},
        provider="deepseek",
        request_model="deepseek/deepseek-chat",
    )

    assert cost.billable_input_tokens == 800
    assert cost.input_cost == 0.0008
    assert cost.output_cost == 0.001
    assert cost.cache_read_cost == 0.000004
    assert cost.total_cost == 0.001804


def test_calculate_cost_keeps_anthropic_input_tokens_as_fresh_tokens():
    usage = extract_usage(
        {
            "usage": {
                "input_tokens": 1000,
                "output_tokens": 500,
                "cache_read_input_tokens": 200,
                "cache_creation_input_tokens": 100,
            }
        }
    )

    cost = calculate_cost(
        usage,
        {"input": 3.0, "output": 15.0, "cache_hit": 0.3, "cache_create": 3.75},
        provider="anthropic",
        request_model="anthropic/claude-sonnet-4",
    )

    assert cost.billable_input_tokens == 1000
    assert cost.input_cost == 0.003
    assert cost.output_cost == 0.0075
    assert cost.cache_read_cost == 0.00006
    assert cost.cache_creation_cost == 0.000375
    assert cost.total_cost == 0.010935


def test_pricing_from_model_converts_legacy_per_1k_columns_to_per_1m():
    model = SimpleNamespace(
        model_id="deepseek-chat",
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.002,
        extra_params={"cost_per_1m_input_cache_hit": 0.02},
    )

    pricing = pricing_from_model(model)

    assert pricing == {
        "input": 1.0,
        "output": 2.0,
        "cache_hit": 0.02,
        "cache_create": None,
    }


def test_pricing_from_model_zeroes_deepseek_v4_flash_free():
    model = SimpleNamespace(
        model_id="opencode/deepseek-v4-flash-free",
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.002,
        extra_params={"cost_per_1m_input_cache_hit": 0.02},
    )

    pricing = pricing_from_model(model)

    assert pricing == {
        "input": 0.0,
        "output": 0.0,
        "cache_hit": 0.0,
        "cache_create": None,
    }


@pytest.mark.asyncio
async def test_record_llm_call_updates_existing_request_id():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        first = await record_llm_call(
            db,
            model=None,
            request_model="openai/test-model",
            scene="analysis",
            status="FAILED",
            duration_ms=120,
            error_message="temporary failure",
            request_id="same-request",
        )
        second = await record_llm_call(
            db,
            model=None,
            request_model="openai/test-model",
            scene="analysis",
            status="DONE",
            duration_ms=240,
            usage=TokenUsage(input_tokens=100, output_tokens=40),
            request_id="same-request",
        )
        result = await db.execute(select(LlmCallLog))
        rows = result.scalars().all()

    assert first.id == second.id
    assert len(rows) == 1
    assert rows[0].status == "DONE"
    assert rows[0].error_message is None
    assert rows[0].input_tokens == 100
    assert rows[0].output_tokens == 40
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_llm_call_in_new_session_writes_directly(monkeypatch):
    calls = {}

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def commit(self):
            calls["committed"] = True

        async def rollback(self):
            calls["rolled_back"] = calls.get("rolled_back", 0) + 1

        async def scalar(self, _stmt):
            calls["scalar_checked"] = calls.get("scalar_checked", 0) + 1
            return None

        def add(self, _log):
            calls["added"] = True

        async def flush(self):
            calls["flushed"] = True

    def fake_async_session():
        return FakeSession()

    monkeypatch.setattr("app.core.database.async_session", fake_async_session)

    await record_llm_call_in_new_session(
        model=None,
        request_model="openai/glm-4-flash",
        scene="content_analysis",
        status="DONE",
        duration_ms=123,
    )

    assert calls["scalar_checked"] == 1
    assert calls["added"] is True
    assert calls["flushed"] is True
    assert calls["committed"] is True
