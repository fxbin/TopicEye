import threading
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api, llm_evaluations as llm_evaluations_api, llm_models as llm_models_api
from app.api.v1.llm_models import (
    LLM_COMPLETION_TIMEOUT_SECONDS,
    ModelCreateRequest,
    ModelUpdateRequest,
    _auto_score_response,
    _completion_kwargs,
    _missing_explicit_api_key,
    _resolve_litellm_model,
    _sample_payload,
)
from app.core.database import Base
from app.models.llm_model import LlmModel, ModelEvaluation
from app.services.auth_service import create_session, create_user
from app.services.llm.model_resolver import resolve_litellm_model
from app.services.llm.presets import apply_model_preset, list_model_presets


@pytest_asyncio.fixture
async def llm_model_client() -> AsyncGenerator[tuple[httpx.AsyncClient, str, str, async_sessionmaker], None]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        free_user = await create_user(db, email="free-model@example.com", password="Password123", role="user")
        pro_user = await create_user(db, email="pro-model@example.com", password="Password123", role="user")
        admin = await create_user(db, email="admin-model@example.com", password="Password123", role="admin")
        pro_user.plan = "pro"
        free_token, _ = await create_session(db, free_user)
        pro_token, _ = await create_session(db, pro_user)
        admin_token, _ = await create_session(db, admin)
        system_model = LlmModel(
            name="System Model",
            provider="openai",
            model_id="gpt-test",
            api_key="system-key",
            enabled=True,
        )
        db.add(system_model)
        await db.commit()

    app = FastAPI()
    app.include_router(llm_models_api.router)
    app.include_router(llm_evaluations_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db
    app.dependency_overrides[llm_models_api.get_db] = override_get_db
    app.dependency_overrides[llm_evaluations_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, free_token, pro_token, admin_token, session_factory

    await engine.dispose()


def test_resolve_litellm_model_adds_provider_prefix_for_plain_model_id():
    model = SimpleNamespace(provider="deepseek", model_id="deepseek-chat", api_base=None)

    assert _resolve_litellm_model(model) == "deepseek/deepseek-chat"


def test_resolve_litellm_model_uses_openai_prefix_for_bigmodel_endpoint():
    model = SimpleNamespace(
        provider="openai",
        model_id="glm-5.1",
        api_base="https://open.bigmodel.cn/api/paas/v4",
    )

    assert _resolve_litellm_model(model) == "openai/glm-5.1"


def test_shared_model_resolver_preserves_already_prefixed_model_id():
    model = SimpleNamespace(provider="deepseek", model_id="deepseek/deepseek-chat", api_base=None)

    assert resolve_litellm_model(model) == "deepseek/deepseek-chat"


def test_shared_model_resolver_routes_opencode_zen_through_openai_compatible_provider():
    model = SimpleNamespace(
        provider="openai",
        model_id="deepseek-v4-flash-free",
        api_base="https://opencode.ai/zen/v1",
    )

    assert resolve_litellm_model(model) == "openai/deepseek-v4-flash-free"


def test_shared_model_resolver_prefers_explicit_litellm_model():
    model = SimpleNamespace(
        provider="custom",
        model_id="opencode/deepseek-v4-flash-free",
        api_base="https://opencode.ai/zen/v1",
        extra_params={"litellm_model": "openai/deepseek-v4-flash-free"},
    )

    assert resolve_litellm_model(model) == "openai/deepseek-v4-flash-free"


def test_completion_kwargs_passes_openai_compatible_timeout_and_endpoint():
    model = SimpleNamespace(
        api_key="test-key",
        api_base="https://opencode.ai/zen/v1",
        extra_params=None,
    )

    kwargs = _completion_kwargs(
        model,
        "openai/deepseek-v4-flash-free",
        [{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=200,
    )

    assert kwargs["model"] == "openai/deepseek-v4-flash-free"
    assert kwargs["api_key"] == "test-key"
    assert kwargs["api_base"] == "https://opencode.ai/zen/v1"
    assert kwargs["timeout"] == LLM_COMPLETION_TIMEOUT_SECONDS


def test_completion_kwargs_merges_explicit_litellm_params():
    model = SimpleNamespace(
        api_key="test-key",
        api_base="https://example.test/v1",
        extra_params={
            "cost_per_1m_input_cache_hit": 0.02,
            "litellm_params": {
                "timeout": 10,
                "custom_llm_provider": "openai",
                "unsupported": "ignored",
            },
        },
    )

    kwargs = _completion_kwargs(
        model,
        "openai/custom-model",
        [{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=200,
    )

    assert kwargs["timeout"] == 10
    assert kwargs["custom_llm_provider"] == "openai"
    assert "unsupported" not in kwargs


def test_model_config_normalizes_blank_api_key_and_endpoint():
    created = ModelCreateRequest(
        name="OpenCode",
        provider="custom",
        model_id="opencode/deepseek-v4-flash-free",
        api_key="   ",
        api_base="  https://opencode.ai/zen/v1  ",
        routing_group="   ",
        model_family="  deepseek ",
        channel_name=" opencode ",
    )
    updated = ModelUpdateRequest(api_key="  real-key  ", api_base="     ")

    assert created.api_key is None
    assert created.api_base == "https://opencode.ai/zen/v1"
    assert created.routing_group == "default"
    assert created.model_family == "deepseek"
    assert created.channel_name == "opencode"
    assert updated.api_key == "real-key"
    assert updated.api_base is None


def test_model_presets_provide_beginner_defaults_and_help():
    catalog = list_model_presets()

    assert catalog["defaults"]["temperature"] == 0.3
    assert catalog["defaults"]["max_tokens"] == 2000
    assert catalog["defaults"]["requests_per_minute"] == 30
    assert catalog["parameter_help"]["temperature"]["label"] == "稳定度"
    assert catalog["parameter_help"]["temperature"]["range"] == [0, 2]
    assert catalog["parameter_help"]["temperature"]["recommended"] == "选题分析推荐 0.3"
    assert catalog["parameter_help"]["temperature"]["when_to_change"]
    assert catalog["parameter_help"]["max_tokens"]["unit"] == "tokens"
    assert catalog["parameter_help"]["requests_per_minute"]["range"] == [1, 120]
    assert catalog["parameter_help"]["cooldown_seconds"]["default"] == 300
    assert catalog["parameter_help"]["cooldown_seconds"]["beginner"] == "默认即可"
    assert catalog["help"]["beginner_tip"]
    assert "稳定度" in catalog["help"]["beginner_tip"]
    assert catalog["help"]["defaults_tip"]
    assert catalog["help"]["advanced_tip"]
    assert "RPM" not in catalog["help"]["rpm_tip"]
    assert "Temperature" not in catalog["help"]["temperature_tip"]
    assert "Max Tokens" not in catalog["help"]["max_tokens_tip"]
    assert {preset["key"] for preset in catalog["presets"]} >= {
        "openai_fast",
        "deepseek_balanced",
        "openai_compatible",
        "custom",
    }

    payload = apply_model_preset({"api_key": "secret"}, "deepseek_balanced")

    assert payload["name"] == "DeepSeek 性价比模型"
    assert payload["provider"] == "deepseek"
    assert payload["model_id"] == "deepseek-chat"
    assert payload["requests_per_minute"] == 20
    assert payload["api_key"] == "secret"


def test_plain_model_request_uses_beginner_safe_defaults():
    request = ModelCreateRequest(name="Manual Model", provider="openai", model_id="gpt-test")

    assert request.temperature == 0.3
    assert request.max_tokens == 2000
    assert request.requests_per_minute == 30


def test_model_request_rejects_unsafe_parameter_overrides():
    with pytest.raises(ValueError):
        ModelCreateRequest(name="Bad Model", provider="openai", model_id="gpt-test", temperature=3)
    with pytest.raises(ValueError):
        ModelCreateRequest(name="Bad Model", provider="openai", model_id="gpt-test", max_tokens=100)
    with pytest.raises(ValueError):
        ModelUpdateRequest(requests_per_minute=0)


def test_missing_explicit_api_key_treats_blank_values_as_missing():
    request = ModelCreateRequest(
        name="OpenCode",
        provider="custom",
        model_id="opencode/deepseek-v4-flash-free",
        api_key="   ",
        api_base="  https://opencode.ai/zen/v1  ",
    )
    model = SimpleNamespace(api_key=request.api_key, api_base=request.api_base)

    assert _missing_explicit_api_key(model) is True


def test_sample_payload_parses_title_and_content_from_json():
    sample = _sample_payload('{"title":"标题","content":"正文"}')

    assert sample == {"title": "标题", "content": "正文"}


def test_auto_score_accepts_fenced_json_and_json_lists():
    assert _auto_score_response('```json\n{"summary":"ok","tags":["a"]}\n```') >= 4
    assert _auto_score_response('[{"title":"a"}]') >= 3


@pytest.mark.asyncio
async def test_evaluation_run_executes_models_with_bounded_concurrency(llm_model_client, monkeypatch):
    client, _free_token, _pro_token, admin_token, session_factory = llm_model_client
    monkeypatch.setattr(llm_models_api, "async_session", session_factory)
    monkeypatch.setattr(llm_evaluations_api, "async_session", session_factory)
    monkeypatch.setattr(llm_models_api.settings, "LLM_WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(llm_evaluations_api.settings, "LLM_WORKER_CONCURRENCY", 2)

    async with session_factory() as db:
        db.add(
            LlmModel(
                name="Second System Model",
                provider="openai",
                model_id="gpt-test-2",
                api_key="system-key-2",
                enabled=True,
            )
        )
        await db.commit()
        result = await db.execute(select(LlmModel.id).order_by(LlmModel.id))
        model_ids = [row[0] for row in result.all()]

    active = 0
    max_active = 0
    lock = threading.Lock()
    both_started = threading.Event()
    release = threading.Event()

    def fake_completion(**_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            if active >= 2:
                both_started.set()
        assert both_started.wait(2)
        release.set()
        with lock:
            active -= 1
        return SimpleNamespace(
            model="fake-model",
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"summary":"ok","tags":["a"]}'))],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )

    monkeypatch.setattr("litellm.completion", fake_completion)

    response = await client.post(
        "/models/evaluations/run",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"model_ids": model_ids, "prompt_type": "analysis"},
    )

    assert response.status_code == 200
    assert max_active == 2
    assert release.is_set()

    async with session_factory() as db:
        result = await db.execute(select(ModelEvaluation).order_by(ModelEvaluation.model_id))
        rows = result.scalars().all()

    assert [row.status for row in rows] == ["DONE", "DONE"]
    assert all(row.response_text for row in rows)
