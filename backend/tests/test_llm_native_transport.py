"""
自有传输层（issue #181）的回归测试。

三组断言：

1. **错误分类与 litellm 判定结论一致**——同样的 provider 响应，在两条路径下
   必须得到同样的编排决策（限流不重试且切下一候选；确定性错误不重试、
   不降级、不污染熔断器）。对照组是**真实 litellm** 的判定结果（用
   ``litellm.aclient_session`` 注入 MockTransport，让 litellm 自己走一遍
   异常映射），不是手写的期望表。
2. **用量提取一致**——同一份 usage 载荷，经两条路径得到相同的 TokenUsage，
   计价口径不因传输实现而漂移。
3. **URL 与请求体一致**——自有路径打到与 litellm 相同的端点、发送同样的
   模型名。

参考：``test_llm_retry_predicate.py``（重试谓词）、``test_llm_call_trace.py``
（用量与轨迹）。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import pytest
from litellm.exceptions import BadRequestError, RateLimitError

from app.services.llm import _call_engine
from app.services.llm._call_engine import _should_retry
from app.services.llm.adapters import (
    LlmAdapterError,
    build_chat_completions_url,
    classify_status_error,
    native_unavailable_reason,
    resolve_wire_model,
    to_litellm_exception,
)
from app.services.llm.adapters.registry import build_native_request
from app.services.llm_usage import extract_usage

# ── 1. 错误分类：自有分类 ↔ litellm 异常 的判定结论必须一致 ────────────────

# (HTTP 状态, provider 响应体) —— 覆盖 litellm 的每一条判定分支
_ERROR_CASES = [
    (429, {"error": {"message": "Rate limit reached for gpt-4"}}),
    (429, {"error": {"message": "请求过于频繁，请稍后再试"}}),
    (400, {"error": {"message": "Invalid request: max_tokens too large"}}),
    (400, {"error": {"code": 1301, "message": "Sensitive content detected", "type": "content_filter"}}),
    (400, {"error": {"message": "This model's maximum context length is 8192 tokens"}}),
    (400, {"error": {"message": "maximum input length is 8192 tokens"}}),
    (400, {"error": {"message": "Current length is 9000 while limit is 8192"}}),
    (400, {"error": {"message": "response_format is not supported by this model"}}),
    (401, {"error": {"message": "Incorrect API key provided"}}),
    (404, {"error": {"message": "model not found"}}),
    (422, {"error": {"message": "unprocessable entity"}}),
    (500, {"error": {"message": "internal server error"}}),
    (502, {"error": {"message": "bad gateway"}}),
    (503, {"error": {"message": "service unavailable"}}),
    (504, {"error": {"message": "gateway timeout"}}),
    (408, {"error": {"message": "request timeout"}}),
    (403, {"error": {"message": "forbidden"}}),
    (405, {"error": {"message": "method not allowed"}}),
    # 状态码闸门：provider 回显的请求体里出现 token id "429" 不算限流
    (400, {"error": {"message": "invalid token id 429"}}),
    # 内容策略分支（litellm 只认这三组特征串）
    (400, {"error": {"type": "invalid_request_error", "code": "content_policy_violation", "message": "rejected"}}),
    (400, {"error": {"message": "Invalid prompt: violating our usage policy"}}),
    (400, {"error": {"message": "Your request was rejected as a result of the safety system"}}),
    # 模型不存在分支
    (400, {"error": {"type": "invalid_request_error", "code": "model_not_found", "message": "no such model"}}),
    # 请求体过大 → 限流
    (400, {"error": {"message": "Request too large"}}),
    # 上下文超窗的两条排除规则：命中排除后回到 400 兜底
    (
        400,
        {
            "error": {
                "code": "string_above_max_length",
                "message": "string too long. expected a string with maximum length",
            }
        },
    ),
    (400, {"error": {"message": "Invalid 'user': string too long"}}),
    # 缺 api key 分支（特征串大小写敏感）
    (
        401,
        {
            "error": {
                "message": "The api_key client option must be set either by passing api_key to the client "
                "or by setting the OPENAI_API_KEY environment variable"
            }
        },
    ),
]


# 每次 parity 调用一个递增序号——用来给 litellm 的 client 缓存键造唯一性。
_PARITY_CALL_SEQ: list[int] = []


async def _litellm_exception_for(status: int, body: dict, monkeypatch):
    """跑一次**真实的 litellm**，取它在同样响应下抛出的异常。

    这里不手写对照表。手写的表只能证明「实现和我的理解一致」，证明不了
    「实现和 litellm 一致」——表写错了，测试照样绿。

    注入点是 litellm 自己的 ``aclient_session``（litellm 1.103.1 的
    ``OpenAIChatCompletion._get_async_http_client`` 会优先用它），把 httpx
    换成 MockTransport 后，litellm 仍走完整的「发请求 → 解析错误 → 映射
    异常类型」链路，拿到的是它真实的判定结论。

    参考 litellm 1.103.1 实测：GLM 的 ``"type": "content_filter"`` 落在
    litellm 的 400 兜底分支 → ``BadRequestError``；litellm 的内容策略分支
    只认 ``content_policy_violation`` / ``violating our usage policy`` /
    ``rejected as a result of the safety system`` 三组特征串。
    """
    import litellm

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=body)

    # litellm 会把 openai SDK client 缓存在内存里（`in_memory_llm_clients_cache`），
    # 缓存键里带**事件循环 id**。pytest-asyncio 每个用例新建一个循环，循环被回收后
    # id 会被复用——于是后来的用例可能命中前一个用例留下的 client，而那个 client
    # 包着已经关闭的 mock 连接，请求直接变成真实网络连接，报 "Connection error."。
    # 实测这条 flake 真的出现过（27 个用例里第 26 个偶发失败）。
    # 这里先清缓存，再用每次唯一的 api_key 让缓存键必然不同，两道保险。
    litellm.in_memory_llm_clients_cache.flush_cache()
    _PARITY_CALL_SEQ.append(1)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(litellm, "aclient_session", client)
    # litellm 默认会往 stdout 打反馈横幅，测试输出里全是噪音。
    monkeypatch.setattr(litellm, "suppress_debug_info", True)
    try:
        await litellm.acompletion(
            model="openai/gpt-4.1-mini",
            messages=[{"role": "user", "content": "x"}],
            api_base="https://api.openai.com/v1",
            api_key=f"test-key-{len(_PARITY_CALL_SEQ)}",
            num_retries=0,
        )
    except Exception as exc:  # noqa: BLE001 — 这里要的就是 litellm 抛出的原始异常
        return exc
    finally:
        await client.aclose()
    raise AssertionError(f"litellm 对 {status} 响应没有抛异常")


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body"), _ERROR_CASES)
async def test_native_error_classification_matches_litellm_decision(status: int, body: dict, monkeypatch):
    """自有路径的错误，在编排层必须得到与 litellm 路径相同的决定。

    编排层只做三个决定：是否重试（``_should_retry``）、是否算确定性请求错
    （``_is_deterministic_request_error``）、失败后是否降级候选。
    """
    native = classify_status_error(status, json.dumps(body))
    litellm_exc = await _litellm_exception_for(status, body, monkeypatch)

    # 自有异常映射后必须与 litellm 同类——编排层的 isinstance 判定才能命中。
    mapped = to_litellm_exception(native, model="m", provider="openai")
    assert type(mapped) is type(litellm_exc), f"{status} 映射类型不一致: {type(mapped)} vs {type(litellm_exc)}"

    # 两条路径的重试判定必须一致。
    assert _should_retry(mapped) is _should_retry(litellm_exc), f"{status} 重试判定不一致"

    # 两条路径的「确定性请求错」判定必须一致。
    assert _call_engine._is_deterministic_request_error(mapped) is _call_engine._is_deterministic_request_error(
        litellm_exc
    ), f"{status} 确定性判定不一致"


def test_unsupported_params_detected_by_client_precheck():
    """模型不支持 response_format 时，客户端预检就拒绝，不发请求。

    与 litellm 的口径一致（客户端参数表预检抛 UnsupportedParamsError），
    让 ``provider.py`` 的「去掉 response_format 重试」分支在两条路径下同样生效。
    """
    from app.services.llm.adapters.openai_compat import supports_response_format

    assert supports_response_format("gpt-4.1-mini") is True
    assert supports_response_format("gpt-4") is False
    assert supports_response_format("gpt-3.5-turbo-16k") is False


def test_server_side_400_stays_bad_request():
    """服务端 400 一律归 BadRequestError——与 litellm 一致。

    litellm 对服务端 400 不做「参数不被支持」的再分类，因此自家路径也不能
    再分类，否则同一响应在两条路径下会得到不同编排结论。
    """
    native = classify_status_error(400, json.dumps({"error": {"message": "response_format is not supported"}}))
    mapped = to_litellm_exception(native, model="m", provider="openai")
    assert type(mapped) is BadRequestError
    assert _call_engine._is_deterministic_request_error(mapped) is True
    assert _should_retry(mapped) is False


def test_content_policy_and_context_window_are_deterministic():
    """内容策略与上下文超窗都是确定性请求错：不重试、不降级、不污染熔断器。"""
    for body in (
        {"error": {"message": "Invalid prompt: violating our usage policy"}},
        {"error": {"message": "This model's maximum context length is 8192 tokens"}},
    ):
        native = classify_status_error(400, json.dumps(body))
        mapped = to_litellm_exception(native, model="m", provider="openai")
        assert _call_engine._is_deterministic_request_error(mapped) is True
        assert _should_retry(mapped) is False


def test_rate_limit_is_not_retried():
    """限流不重试（由 failover 切下一候选），两条路径一致。"""
    native = classify_status_error(429, json.dumps({"error": {"message": "Rate limit reached"}}))
    mapped = to_litellm_exception(native, model="m", provider="openai")
    assert _should_retry(mapped) is False


# ── 2. 用量提取：两条路径得到相同的 TokenUsage ────────────────────────────────

_USAGE_PAYLOAD = {
    "prompt_tokens": 120,
    "completion_tokens": 45,
    "total_tokens": 165,
    "prompt_tokens_details": {"cached_tokens": 30},
}


def test_usage_extraction_identical_for_both_paths():
    """同一份 usage 载荷，经自有路径与 litellm 路径得到相同的 TokenUsage。

    用量口径直接决定计价，两条路径必须算出同一个结果。
    """
    # 自有路径：provider 原始 usage dict。
    native_response = SimpleNamespace(
        model="provider-reported-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=_USAGE_PAYLOAD,
    )
    # litellm 路径：usage 挂在对象上，字段同名。
    litellm_response = SimpleNamespace(
        model="provider-reported-model",
        choices=[SimpleNamespace(message=SimpleNamespace(content="ok"))],
        usage=SimpleNamespace(**_USAGE_PAYLOAD),
    )

    native_usage = extract_usage(native_response)
    litellm_usage = extract_usage(litellm_response)

    assert native_usage == litellm_usage
    assert native_usage.input_tokens == 120
    assert native_usage.output_tokens == 45
    assert native_usage.cache_read_tokens == 30
    assert native_usage.actual_model == "provider-reported-model"


# ── 3. URL 与模型名：与 litellm 一致 ────────────────────────────────────────


def test_chat_completions_url_matches_litellm_rule():
    """URL 拼接与 litellm 的 get_complete_url 同规则。"""
    assert build_chat_completions_url("https://api.openai.com/v1") == "https://api.openai.com/v1/chat/completions"
    # 尾部斜杠先去掉，不产生双斜杠。
    assert build_chat_completions_url("https://api.openai.com/v1/") == "https://api.openai.com/v1/chat/completions"
    # 已含端点则原样使用。
    already = "https://api.openai.com/v1/chat/completions"
    assert build_chat_completions_url(already) == already


@pytest.mark.parametrize(
    ("model_id", "provider", "expected"),
    [
        ("minicpm5-2b", "custom", "minicpm5-2b"),
        ("example-org/example-29b", "custom", "example-org/example-29b"),
        ("glm-5.1", "openai", "glm-5.1"),
        ("openai/gpt-4", "openai", "gpt-4"),
        ("deepseek-chat", "deepseek", "deepseek-chat"),
    ],
)
def test_wire_model_strips_provider_prefix(model_id: str, provider: str, expected: str):
    """发给 provider 的模型名要剥掉 provider 前缀，但组织/模型命名原样保留。"""
    assert resolve_wire_model(model_id, provider) == expected


# ── 4. 自有路径的可用性判定 ────────────────────────────────────────────────


def _model(provider: str = "custom", model_id: str = "minicpm5-2b", api_base: str | None = None, extra=None):
    return SimpleNamespace(provider=provider, model_id=model_id, api_base=api_base, extra_params=extra)


def test_openai_compatible_provider_supports_native():
    assert native_unavailable_reason(_model("custom", api_base="https://gw.example.com/v1")) is None
    assert native_unavailable_reason(_model("openai", "gpt-4.1-mini")) is None


def test_non_openai_protocol_provider_is_unsupported():
    """azure / bedrock / vertex_ai 协议与认证不同，没有自有实现（#190）。

    anthropic 与 gemini 自 #185 起有自有协议实现，不在这份名单里。
    """
    for provider in ("azure", "bedrock", "vertex_ai"):
        reason = native_unavailable_reason(_model(provider, api_base="https://x.example.com"))
        assert reason is not None
        assert provider in reason


def test_missing_api_base_rejected_unless_default_gateway_exists():
    """缺 api_base 时：有策展默认网关的 provider 可走，没有的（如 custom）显式拒绝。"""
    assert native_unavailable_reason(_model("custom")) is not None
    # deepseek 的默认网关来自精选目录，自有路径可直接走。
    assert native_unavailable_reason(_model("deepseek")) is None


def test_default_api_bases_match_curated_catalog():
    """DEFAULT_API_BASES 与模型目录的精选默认网关不得漂移（两处真源的守卫）。

    目录侧没给默认网关的厂商（anthropic / gemini / xai / mistral），registry
    补官方端点；多个 OpenAI 兼容网关共用 provider=openai，默认只指官方端点。
    """
    from app.services.llm.adapters import DEFAULT_API_BASES
    from app.services.model_catalog_service import FEATURED_PROVIDERS

    for featured in FEATURED_PROVIDERS:
        if featured.default_api_base is None or featured.litellm_provider == "openai":
            continue
        assert DEFAULT_API_BASES.get(featured.litellm_provider) == featured.default_api_base, featured.litellm_provider


def test_explicit_litellm_route_string_is_rejected():
    """配置了 litellm 专属路由串时拒绝——那是 litellm 的路由约定，不在自有路径解释。"""
    model = _model("custom", api_base="https://gw.example.com/v1", extra={"litellm_model": "openai/foo"})
    assert native_unavailable_reason(model) is not None


def test_litellm_only_params_are_rejected():
    """会改变协议或路由语义的 litellm_params 一律拒绝，提示改配置。"""
    for params in (
        {"api_version": "2024-02-01"},
        {"custom_llm_provider": "azure"},
        {"drop_params": True},
    ):
        model = _model("custom", api_base="https://gw.example.com/v1", extra={"litellm_params": params})
        assert native_unavailable_reason(model) is not None, params


def test_header_only_litellm_params_are_honored():
    """只影响请求头的 litellm_params 可由自有路径如实复刻。"""
    model = _model(
        "custom", api_base="https://gw.example.com/v1", extra={"litellm_params": {"extra_headers": {"X-A": "1"}}}
    )
    assert native_unavailable_reason(model) is None


def test_num_retries_param_is_tolerated():
    """litellm_params.num_retries 已无意义（重试全在编排层），带这个键不再拒绝。"""
    model = _model("custom", api_base="https://gw.example.com/v1", extra={"litellm_params": {"num_retries": 4}})
    assert native_unavailable_reason(model) is None


# ── 5. 传输执行 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_call_llm_single_uses_own_transport(monkeypatch):
    """主链路经 _call_engine 走自有传输实现。"""
    captured: dict = {}

    async def fake_complete(self, request):
        captured["url"] = build_chat_completions_url(request.base_url)
        captured["model"] = request.model
        captured["api_key"] = request.api_key
        return SimpleNamespace(
            model="provider-reported",
            choices=[SimpleNamespace(message=SimpleNamespace(content="native-ok"))],
            usage={"prompt_tokens": 1, "completion_tokens": 2},
        )

    monkeypatch.setattr(
        "app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete",
        fake_complete,
    )

    model_config = _model("custom", "minicpm5-2b", api_base="https://gw.example.com/v1")
    content = await _call_engine._call_llm_single(
        messages=[{"role": "user", "content": "hi"}],
        model="openai/minicpm5-2b",
        api_key="secret-key",
        api_base="https://gw.example.com/v1",
        temperature=0.3,
        max_tokens=100,
        response_format=None,
        model_config=model_config,
    )

    assert content == "native-ok"
    assert captured["url"] == "https://gw.example.com/v1/chat/completions"
    assert captured["model"] == "minicpm5-2b"
    assert captured["api_key"] == "secret-key"


@pytest.mark.asyncio
async def test_transport_error_maps_to_litellm_exception(monkeypatch):
    """自有路径的错误必须映射回 litellm 异常类型，编排层判定才不变。"""
    from app.services.llm.adapters.errors import LlmRateLimitError

    async def fake_complete(self, request):
        raise LlmRateLimitError("Rate limit reached", status_code=429, body="rate limited")

    monkeypatch.setattr("app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete", fake_complete)

    model_config = _model("custom", "minicpm5-2b", api_base="https://gw.example.com/v1")
    with pytest.raises(RateLimitError):
        await _call_engine._call_llm_single(
            messages=[{"role": "user", "content": "hi"}],
            model="openai/minicpm5-2b",
            api_key="k",
            api_base="https://gw.example.com/v1",
            temperature=0.3,
            max_tokens=100,
            response_format=None,
            model_config=model_config,
        )


@pytest.mark.asyncio
async def test_unsupported_provider_raises_configuration_error(monkeypatch):
    """不支持的 provider 显式报配置错误，不静默换路、也不碰网络。

    用 vertex_ai 举例——它的认证与端点跟第一方不同，没有自有实现（#190）。
    """
    from app.services.llm.adapters.errors import LlmConfigurationError

    async def fail_complete(self, request):
        raise AssertionError("transport must not be reached for an unsupported provider")

    monkeypatch.setattr("app.services.llm.adapters.openai_compat.OpenAICompatAdapter.complete", fail_complete)

    model_config = _model("vertex_ai", "gemini-2.5-flash", api_base="https://x.example.com")
    with pytest.raises(LlmConfigurationError, match="vertex_ai"):
        await _call_engine._call_llm_single(
            messages=[{"role": "user", "content": "hi"}],
            model="vertex_ai/gemini-2.5-flash",
            api_key="k",
            api_base="https://x.example.com",
            temperature=0.3,
            max_tokens=100,
            response_format=None,
            model_config=model_config,
        )


def test_configuration_error_is_candidate_level_not_request_level():
    """配置错误是候选级问题：不做 tenacity 重试，但也不是「换路无解」的确定性
    请求错——failover 应冷却该候选并尝试下一个，而不是直接放弃。"""
    from app.services.llm.adapters.errors import LlmConfigurationError

    exc = LlmConfigurationError("provider azure 没有自有协议实现")
    assert _should_retry(exc) is False
    assert _call_engine._is_deterministic_request_error(exc) is False


# ── 6. 自有传输实现的请求体与响应归一化 ──────────────────────────────────────


@pytest.mark.asyncio
async def test_openai_compat_request_body_and_headers(monkeypatch):
    """请求体字段与 litellm 对 OpenAI 兼容族发出的完全一致。"""
    from app.services.llm.adapters.openai_compat import OpenAICompatAdapter

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content.decode())
        captured["headers"] = dict(request.headers)
        return httpx.Response(
            200,
            json={
                "model": "provider-reported",
                "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 3, "completion_tokens": 4},
            },
        )

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    adapter = OpenAICompatAdapter()
    request = build_native_request(
        _model("custom", "minicpm5-2b", api_base="https://gw.example.com/v1"),
        messages=[{"role": "user", "content": "hi"}],
        api_key="secret-key",
        api_base="https://gw.example.com/v1",
        temperature=0.3,
        max_tokens=100,
        response_format={"type": "json_object"},
        timeout=5.0,
    )
    response = await adapter.complete(request)

    assert captured["url"] == "https://gw.example.com/v1/chat/completions"
    assert captured["body"] == {
        "model": "minicpm5-2b",
        "messages": [{"role": "user", "content": "hi"}],
        "temperature": 0.3,
        "max_tokens": 100,
        "response_format": {"type": "json_object"},
    }
    assert captured["headers"]["authorization"] == "Bearer secret-key"

    # 响应归一化后与 litellm 的读取形状一致。
    assert response.choices[0].message.content == "hello"
    assert response.model == "provider-reported"
    assert extract_usage(response).input_tokens == 3
    assert extract_usage(response).output_tokens == 4


@pytest.mark.asyncio
async def test_openai_compat_raises_on_http_error(monkeypatch):
    """HTTP 错误必须抛自有错误类型，且带上状态码与消息。"""
    from app.services.llm.adapters.openai_compat import OpenAICompatAdapter

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "Rate limit reached"}})

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)

    adapter = OpenAICompatAdapter()
    request = build_native_request(
        _model("custom", "minicpm5-2b", api_base="https://gw.example.com/v1"),
        messages=[{"role": "user", "content": "hi"}],
        api_key="k",
        api_base="https://gw.example.com/v1",
        temperature=0.3,
        max_tokens=100,
        response_format=None,
        timeout=5.0,
    )
    with pytest.raises(LlmAdapterError) as exc_info:
        await adapter.complete(request)

    assert exc_info.value.status_code == 429
    assert "Rate limit reached" in str(exc_info.value)
