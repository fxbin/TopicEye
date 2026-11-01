import asyncio
from collections.abc import AsyncGenerator
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
import app.services.llm.model_resolver as model_resolver_module
from app.api.v1 import auth as auth_api, llm_evaluations as llm_evaluations_api, llm_models as llm_models_api
from app.api.v1.llm_models import (
    LLM_COMPLETION_TIMEOUT_SECONDS,
    ModelCreateRequest,
    ModelUpdateRequest,
    _auto_score_response,
    _missing_explicit_api_key,
    _resolve_litellm_model,
    _sample_payload,
    _summarize_llm_error,
)
from app.core.database import Base
from app.models.llm_model import LlmModel, ModelEvaluation
from app.services.auth_service import create_session, create_user
from app.services.llm.adapters.base import AdapterChoice, AdapterMessage, AdapterResponse
from app.services.llm.model_resolver import normalize_api_base, resolve_litellm_model
from app.services.llm.presets import apply_model_preset, list_model_presets
from app.services.llm.provider import complete_once


@pytest.fixture
def native_capture(monkeypatch):
    """把自有传输层的 complete 换成记录器，返回捕获到的 NativeRequest 列表。"""
    captured: list = []

    async def fake_complete(self, request):
        captured.append(request)
        return AdapterResponse(
            choices=[AdapterChoice(message=AdapterMessage(content='{"summary":"ok","tags":["a"]}'))],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            model=request.model,
        )

    monkeypatch.setattr("app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete", fake_complete)
    return captured


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


def test_shared_model_resolver_routes_slash_namespaced_custom_model_as_openai():
    """#83：组织/模型命名（example-org/example-29b）在 custom 预设下必须走
    OpenAI 兼容路由，原样透传会被 litellm 当未知 provider 拒绝。"""
    model = SimpleNamespace(
        provider="custom",
        model_id="example-org/example-29b",
        api_base="https://api.example-gateway.test/v1",
    )

    assert resolve_litellm_model(model) == "openai/example-org/example-29b"


def test_shared_model_resolver_routes_slash_namespaced_model_with_explicit_provider():
    """显式 provider（如 openai 预设 + 自定义网关）时，组织/模型命名按该 provider 路由。"""
    model = SimpleNamespace(
        provider="openai",
        model_id="example-org/example-29b",
        api_base="https://api.example-gateway.test/v1",
    )

    assert resolve_litellm_model(model) == "openai/example-org/example-29b"


def test_shared_model_resolver_dedupes_provider_prefix():
    """模型名已带同 provider 前缀时不重复拼接。"""
    model = SimpleNamespace(provider="openai", model_id="openai/gpt-4.1-mini", api_base=None)

    assert resolve_litellm_model(model) == "openai/gpt-4.1-mini"


def test_shared_model_resolver_keeps_slash_model_id_with_known_provider_prefix():
    """无 provider 信息 + 首段命中 litellm 已知 provider：保持原样（显式路由串）。"""
    model = SimpleNamespace(provider="", model_id="deepseek/deepseek-chat", api_base=None)

    assert resolve_litellm_model(model) == "deepseek/deepseek-chat"


def test_shared_model_resolver_falls_back_to_openai_for_unknown_slash_prefix():
    """#83 应用层兜底：无 provider 信息 + 首段不是已知 provider（组织/模型命名，
    或 provider 拼写错误）→ 走 OpenAI 兼容路由而非原样透传。"""
    model = SimpleNamespace(
        provider="",
        model_id="example-org/example-29b",
        api_base="https://api.example-gateway.test/v1",
    )

    assert resolve_litellm_model(model) == "openai/example-org/example-29b"


def test_shared_model_resolver_falls_back_to_openai_for_typoed_provider_prefix():
    """拼写错误的前缀（antrhopic）也走兜底：错误会表现为网关/OpenAI 的
    model-not-found，而不是 litellm 的路由拒绝（应用层取舍，见 #83 评论）。"""
    model = SimpleNamespace(provider="", model_id="antrhopic/claude-sonnet-4", api_base=None)

    assert resolve_litellm_model(model) == "openai/antrhopic/claude-sonnet-4"


def test_shared_model_resolver_routes_bare_custom_provider_as_openai_compatible():
    # "完全自定义"预设落库的 provider=custom + 裸模型名：litellm 没有 custom
    # provider，唯一可行路由是 OpenAI 兼容网关。
    model = SimpleNamespace(
        provider="custom",
        model_id="minicpm5-2b",
        api_base="http://localhost:40114/olla/openai/v1",
        extra_params=None,
    )

    assert resolve_litellm_model(model) == "openai/minicpm5-2b"


def test_normalize_api_base_rewrites_loopback_hosts_inside_container(monkeypatch):
    monkeypatch.setattr(model_resolver_module, "_container_env", True)
    monkeypatch.setattr(model_resolver_module, "_rewrite_logged", set())

    assert (
        normalize_api_base("http://localhost:40114/olla/openai/v1")
        == "http://host.docker.internal:40114/olla/openai/v1"
    )
    assert normalize_api_base("http://127.0.0.1:11434/v1") == "http://host.docker.internal:11434/v1"
    # 远程主机与非容器场景原样返回
    assert normalize_api_base("https://api.example.com/v1") == "https://api.example.com/v1"
    assert normalize_api_base(None) is None


def test_normalize_api_base_passthrough_outside_container(monkeypatch):
    monkeypatch.setattr(model_resolver_module, "_container_env", False)

    assert normalize_api_base("http://localhost:40114/v1") == "http://localhost:40114/v1"


@pytest.mark.asyncio
async def test_complete_once_normalizes_loopback_api_base(monkeypatch, native_capture):
    monkeypatch.setattr(model_resolver_module, "_container_env", True)
    monkeypatch.setattr(model_resolver_module, "_rewrite_logged", set())
    model = SimpleNamespace(
        provider="custom",
        model_id="minicpm5-2b",
        api_key="test-key",
        api_base="http://localhost:40114/olla/openai/v1",
        extra_params=None,
    )

    await complete_once(model, [{"role": "user", "content": "hello"}], temperature=0.3, max_tokens=200)

    assert native_capture[0].base_url == "http://host.docker.internal:40114/olla/openai/v1"


def test_summarize_llm_error_strips_traceback_and_adds_connection_hint():
    raw = (
        "litellm.APIConnectionError: CustomException - [Errno 111] Connection refused\n"
        "Traceback (most recent call last):\n  ...many lines..."
    )

    summarized = _summarize_llm_error(RuntimeError(raw))

    assert "Traceback" not in summarized
    assert "Connection refused" in summarized
    assert "host.docker.internal" in summarized


def test_summarize_llm_error_adds_hint_for_not_found():
    summarized = _summarize_llm_error(RuntimeError("404 Not Found: no route"))

    assert "/v1" in summarized


@pytest.mark.asyncio
async def test_complete_once_passes_endpoint_key_and_probe_timeout(native_capture):
    model = SimpleNamespace(
        provider="custom",
        model_id="deepseek-v4-flash-free",
        api_key="test-key",
        api_base="https://opencode.ai/zen/v1",
        extra_params=None,
    )

    await complete_once(
        model,
        [{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=200,
        timeout=LLM_COMPLETION_TIMEOUT_SECONDS,
    )

    request = native_capture[0]
    assert request.model == "deepseek-v4-flash-free"
    assert request.api_key == "test-key"
    assert request.base_url == "https://opencode.ai/zen/v1"
    assert request.timeout == LLM_COMPLETION_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_complete_once_lets_configured_timeout_and_headers_override_defaults(native_capture):
    model = SimpleNamespace(
        provider="custom",
        model_id="custom-model",
        api_key="test-key",
        api_base="https://example.test/v1",
        extra_params={
            "cost_per_1m_input_cache_hit": 0.02,
            "litellm_params": {"timeout": 10, "extra_headers": {"X-Tenant": "demo"}},
        },
    )

    await complete_once(
        model,
        [{"role": "user", "content": "hello"}],
        temperature=0.3,
        max_tokens=200,
        timeout=LLM_COMPLETION_TIMEOUT_SECONDS,
    )

    request = native_capture[0]
    assert request.timeout == 10
    assert request.headers["X-Tenant"] == "demo"


@pytest.mark.asyncio
async def test_complete_once_is_a_single_attempt(monkeypatch):
    """探测与评测不重试、不 failover：适配器抛限流就原样抛出，且只打了一次。"""
    from app.services.llm.adapters.errors import LlmRateLimitError

    calls = 0

    async def failing_complete(self, request):
        nonlocal calls
        calls += 1
        raise LlmRateLimitError("rate limited", status_code=429)

    monkeypatch.setattr("app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete", failing_complete)
    model = SimpleNamespace(
        provider="custom",
        model_id="custom-model",
        api_key="test-key",
        api_base="https://example.test/v1",
        extra_params=None,
    )

    with pytest.raises(LlmRateLimitError):
        await complete_once(model, [{"role": "user", "content": "hello"}], temperature=0.3, max_tokens=16)

    assert calls == 1


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
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def fake_complete(self, request):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        if active >= 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), 2)
        release.set()
        active -= 1
        return AdapterResponse(
            choices=[AdapterChoice(message=AdapterMessage(content='{"summary":"ok","tags":["a"]}'))],
            usage={"prompt_tokens": 10, "completion_tokens": 5},
            model=request.model,
        )

    monkeypatch.setattr("app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete", fake_complete)

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


@pytest.mark.asyncio
async def test_model_ping_goes_through_shared_transport_dispatch(llm_model_client, monkeypatch, native_capture):
    """连通性探测与主链路同一条传输路径：探测通过 = 生产那条路通。"""
    client, _free_token, _pro_token, admin_token, session_factory = llm_model_client
    monkeypatch.setattr(llm_models_api, "async_session", session_factory)

    async with session_factory() as db:
        model_id = (await db.execute(select(LlmModel.id).order_by(LlmModel.id))).scalars().first()

    response = await client.post(f"/models/{model_id}/test", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["model_name"] == "System Model"

    request = native_capture[0]
    assert request.model == "gpt-test"
    assert request.base_url == "https://api.openai.com/v1"
    assert request.api_key == "system-key"
    assert request.max_tokens == 16
    assert request.timeout == LLM_COMPLETION_TIMEOUT_SECONDS
