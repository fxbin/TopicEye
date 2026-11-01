"""anthropic / gemini 原生协议的自有传输层（issue #185）回归测试。

与 #181 的 OpenAI 兼容族测试同一套方法：**对照组是真实 litellm**，不是手写的
期望表——手写的表只能证明「实现和我的理解一致」，证明不了「实现和 litellm
一致」。

litellm 的 anthropic / gemini 路径走自己的 ``AsyncHTTPHandler``（内部新建
``httpx.AsyncClient``），所以对照的做法是拦 httpx 这一层：让 litellm 真的
发一次请求，抓下它发出的 URL / 头 / 请求体与它抛出的异常，再与自家路径逐条
比。

四组断言：

1. **请求 parity**：URL、鉴权头、请求体逐字段一致。
2. **错误分类 parity**：同一响应下，异常类型与编排结论（是否重试、是否算
   确定性错误）都一致。
3. **响应归一化**：文本块拼接与 usage 提取。
4. **计费口径**：anthropic 的 input 不含缓存、缓存读写单独计价——这是 Anthropic
   API 的原生口径，也与本仓库 ``_input_tokens_include_cache`` 的 anthropic
   分支一致。
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import httpx
import litellm
import pytest

from app.services.llm import _call_engine
from app.services.llm._call_engine import _should_retry
from app.services.llm.adapters import (
    build_generate_content_url,
    build_messages_url,
    classify_anthropic_error,
    classify_gemini_error,
    native_unavailable_reason,
    resolve_protocol,
)
from app.services.llm.adapters.anthropic_native import AnthropicNativeAdapter, build_request_body as anthropic_body
from app.services.llm.adapters.base import NativeRequest
from app.services.llm.adapters.gemini_native import GeminiNativeAdapter, build_request_body as gemini_body
from app.services.llm_usage import calculate_cost, extract_usage
from tests.llm_parity_oracle import legacy_is_deterministic_request_error, legacy_should_retry

# ── 请求级对照用的报文 ──────────────────────────────────────────────────────

_MESSAGES = [
    {"role": "system", "content": "sys prompt"},
    {"role": "user", "content": "hi"},
    {"role": "assistant", "content": "yo"},
    {"role": "user", "content": "more"},
]

_ANTHROPIC_OK = {
    "id": "msg_1",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-5",
    "content": [{"type": "text", "text": "hello"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 100, "output_tokens": 50},
}

_GEMINI_OK = {
    "candidates": [
        {"content": {"parts": [{"text": "hello"}], "role": "model"}, "finishReason": "STOP", "index": 0},
    ],
    "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 50, "totalTokenCount": 150},
    "modelVersion": "gemini-2.5-flash",
}

# 只比这些头——其余是 litellm / httpx 自己的默认头，没有可比性。
_COMPARED_HEADERS = ("content-type", "x-api-key", "anthropic-version", "x-goog-api-key", "authorization")


@pytest.fixture
def http_capture(monkeypatch):
    """把 httpx 请求拦在本地：记录 URL / 头 / 体，并按 ``state`` 返回响应。

    litellm 把 http handler 缓存在进程级字典里，缓存键带**事件循环 id**——
    循环被回收后 id 会复用，于是后来的用例可能命中前一个用例留下的 client
    （它的 transport 指向旧的捕获器）。所以每次用例开始前清掉缓存。
    """
    captured: list[dict] = []
    state = {"status": 200, "json": {}}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "url": str(request.url),
                "headers": {k.lower(): v for k, v in request.headers.items()},
                "body": json.loads(request.content.decode()) if request.content else None,
            }
        )
        return httpx.Response(state["status"], json=state["json"])

    original = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return original(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", patched)
    litellm.in_memory_llm_clients_cache.flush_cache()
    litellm.suppress_debug_info = True
    try:
        yield captured, state
    finally:
        litellm.in_memory_llm_clients_cache.flush_cache()


async def _litellm_acompletion(model: str, **kwargs):
    """跑一次真实 litellm，返回它抛出的异常（没抛则 None）。"""
    try:
        await litellm.acompletion(
            model=model,
            messages=_MESSAGES,
            api_key="test-key",
            temperature=0.3,
            max_tokens=200,
            num_retries=0,
            **kwargs,
        )
    except Exception as exc:  # noqa: BLE001 — 这里要的就是 litellm 抛出的原始异常
        return exc
    return None


def _model(provider: str = "anthropic", model_id: str = "claude-sonnet-4-5", api_base: str | None = None, extra=None):
    return SimpleNamespace(provider=provider, model_id=model_id, api_base=api_base, extra_params=extra)


def _native_request(provider: str, model_id: str, base_url: str, response_format=None) -> NativeRequest:
    return NativeRequest(
        model=model_id,
        base_url=base_url,
        api_key="test-key",
        messages=_MESSAGES,
        temperature=0.3,
        max_tokens=200,
        response_format=response_format,
        timeout=5.0,
        headers={},
    )


# ── 1. 请求 parity：URL / 头 / 请求体 ───────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_request_matches_litellm(http_capture):
    """anthropic：URL、鉴权头、请求体与 litellm 发出的完全一致。"""
    captured, state = http_capture
    state["json"] = _ANTHROPIC_OK

    await _litellm_acompletion("anthropic/claude-sonnet-4-5")
    assert len(captured) == 1
    litellm_request = captured[0]

    request = _native_request("anthropic", "claude-sonnet-4-5", "https://api.anthropic.com")
    await AnthropicNativeAdapter().complete(request)
    native_request = captured[-1]

    assert native_request["url"] == litellm_request["url"] == "https://api.anthropic.com/v1/messages"
    for header in _COMPARED_HEADERS:
        assert native_request["headers"].get(header) == litellm_request["headers"].get(header), header
    assert native_request["body"] == litellm_request["body"]


@pytest.mark.asyncio
async def test_gemini_request_matches_litellm(http_capture):
    """gemini：URL、鉴权头、请求体与 litellm 发出的完全一致。"""
    captured, state = http_capture
    state["json"] = _GEMINI_OK

    await _litellm_acompletion("gemini/gemini-2.5-flash")
    assert len(captured) == 1
    litellm_request = captured[0]

    request = _native_request("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta")
    await GeminiNativeAdapter().complete(request)
    native_request = captured[-1]

    assert native_request["url"] == litellm_request["url"]
    assert (
        native_request["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    for header in _COMPARED_HEADERS:
        assert native_request["headers"].get(header) == litellm_request["headers"].get(header), header
    assert native_request["body"] == litellm_request["body"]


def test_anthropic_request_body_shape():
    """system 抽到顶层、content 是 text 块数组、response_format 被丢弃。

    litellm 对 anthropic **静默丢弃** response_format（实测请求体里没有），
    自家路径照做——不静默丢弃 litellm 丢弃的东西。
    """
    request = _native_request("anthropic", "claude-sonnet-4-5", "https://api.anthropic.com")
    body = anthropic_body(request)
    assert body == {
        "model": "claude-sonnet-4-5",
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            {"role": "assistant", "content": [{"type": "text", "text": "yo"}]},
            {"role": "user", "content": [{"type": "text", "text": "more"}]},
        ],
        "max_tokens": 200,
        "temperature": 0.3,
        "system": [{"type": "text", "text": "sys prompt"}],
    }
    assert build_messages_url("https://api.anthropic.com/v1/messages") == "https://api.anthropic.com/v1/messages"


def test_gemini_request_body_shape():
    """assistant 的角色名是 model、system 走 system_instruction、json_object 走 response_mime_type。"""
    request = _native_request("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta")
    body = gemini_body(request)
    assert body == {
        "contents": [
            {"role": "user", "parts": [{"text": "hi"}]},
            {"role": "model", "parts": [{"text": "yo"}]},
            {"role": "user", "parts": [{"text": "more"}]},
        ],
        "generationConfig": {"temperature": 0.3, "max_output_tokens": 200},
        "system_instruction": {"parts": [{"text": "sys prompt"}]},
    }
    # json_object 映射成 response_mime_type（proto3 的 JSON 映射同时接受
    # camelCase 与原名 snake_case，litellm 一直这么发）。
    request = _native_request(
        "gemini",
        "gemini-2.5-flash",
        "https://generativelanguage.googleapis.com/v1beta",
        response_format={"type": "json_object"},
    )
    assert gemini_body(request)["generationConfig"]["response_mime_type"] == "application/json"
    assert (
        build_generate_content_url("https://g.example.com/v1beta", "m")
        == "https://g.example.com/v1beta/models/m:generateContent"
    )


# ── 2. 错误分类 parity ──────────────────────────────────────────────────────

_ANTHROPIC_ERROR_CASES = [
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "max_tokens: must be > 0"}}),
    (
        400,
        {"type": "error", "error": {"type": "invalid_request_error", "message": "prompt is too long: 250000 tokens"}},
    ),
    (401, {"type": "error", "error": {"type": "authentication_error", "message": "Invalid API Key"}}),
    (403, {"type": "error", "error": {"type": "permission_error", "message": "not allowed"}}),
    (404, {"type": "error", "error": {"type": "not_found_error", "message": "model not found"}}),
    (413, {"type": "error", "error": {"type": "request_too_large", "message": "too large"}}),
    (
        429,
        {
            "type": "error",
            "error": {
                "type": "rate_limit_error",
                "message": "Number of request tokens has exceeded your per-minute rate limit",
            },
        },
    ),
    (500, {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}),
    (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}),
    (400, {"type": "error", "error": {"type": "invalid_request_error", "message": "content filtering policy"}}),
]

_GEMINI_ERROR_CASES = [
    (400, {"error": {"code": 400, "message": "Invalid JSON payload received.", "status": "INVALID_ARGUMENT"}}),
    (
        400,
        {"error": {"code": 400, "message": "The input token count exceeds the maximum", "status": "INVALID_ARGUMENT"}},
    ),
    (401, {"error": {"code": 401, "message": "API key not valid", "status": "UNAUTHENTICATED"}}),
    (403, {"error": {"code": 403, "message": "Permission denied", "status": "PERMISSION_DENIED"}}),
    (404, {"error": {"code": 404, "message": "models/gemini-x is not found", "status": "NOT_FOUND"}}),
    (429, {"error": {"code": 429, "message": "Resource has been exhausted", "status": "RESOURCE_EXHAUSTED"}}),
    # 命中 litellm 的配额特征串（"Quota exceeded for"）——上面那条 Google 措辞
    # "Resource has been exhausted" 其实**不**匹配 litellm 名单里的
    # "Resource exhausted"，两者都落到 429 状态码兜底，结论相同但走的分支不同。
    (
        429,
        {
            "error": {
                "code": 429,
                "message": "Quota exceeded for quota metric 'Generate requests'",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    ),
    # 上游网关把 429 包在 5xx 外壳里——litellm 的限流闸门只对 5xx 生效。
    (503, {"error": {"code": 429, "message": "upstream wrapped 429", "status": "RESOURCE_EXHAUSTED"}}),
    # 特征串命中但状态码不是 429——litellm 判限流，状态码兜底会判请求错。
    # 这条分支与 429 的那条**结论相同**（都是 RateLimitError），所以只有非 429
    # 状态才能观测到它：429 那条即使规则失效，类型也不变，测试不会红。
    (
        400,
        {
            "error": {
                "code": 400,
                "message": "Quota exceeded for quota metric 'Generate requests'",
                "status": "RESOURCE_EXHAUSTED",
            }
        },
    ),
    (500, {"error": {"code": 500, "message": "Internal error encountered.", "status": "INTERNAL"}}),
    (503, {"error": {"code": 503, "message": "The model is overloaded", "status": "UNAVAILABLE"}}),
]


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body"), _ANTHROPIC_ERROR_CASES)
async def test_anthropic_error_classification_matches_litellm(http_capture, status, body):
    """同一响应下，自有路径与 litellm 的异常类型和编排结论都一致。

    anthropic 的 403 特别值得盯：litellm 给 ``PermissionDeniedError``，
    而这个类型**不在**编排层的确定性错误清单里——403 在 anthropic 路径下是
    可重试的。自家路径若归成 ``BadRequestError``，403 就会从「重试」变成
    「不重试」。
    """
    _, state = http_capture
    state["status"] = status
    state["json"] = body

    litellm_exc = await _litellm_acompletion("anthropic/claude-sonnet-4-5")
    assert litellm_exc is not None

    native = classify_anthropic_error(status, json.dumps(body))

    assert _should_retry(native) is legacy_should_retry(litellm_exc), f"{status} 重试判定不一致"
    assert _call_engine._is_deterministic_request_error(native) is legacy_is_deterministic_request_error(
        litellm_exc
    ), f"{status} 确定性判定不一致"


@pytest.mark.asyncio
@pytest.mark.parametrize(("status", "body"), _GEMINI_ERROR_CASES)
async def test_gemini_error_classification_matches_litellm(http_capture, status, body):
    """同一响应下，自有路径与 litellm 的异常类型和编排结论都一致。

    gemini 的 403 与 anthropic 相反：litellm 给 ``BadRequestError``（响应体里
    出现 "403" 字样即命中），不是 ``PermissionDeniedError``——403 是否算
    确定性错误因此相反，必须逐字复刻。
    """
    _, state = http_capture
    state["status"] = status
    state["json"] = body

    litellm_exc = await _litellm_acompletion("gemini/gemini-2.5-flash")
    assert litellm_exc is not None

    native = classify_gemini_error(status, json.dumps(body))

    assert _should_retry(native) is legacy_should_retry(litellm_exc), f"{status} 重试判定不一致"
    assert _call_engine._is_deterministic_request_error(native) is legacy_is_deterministic_request_error(
        litellm_exc
    ), f"{status} 确定性判定不一致"


# ── 3. 响应归一化 ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_anthropic_response_normalization(http_capture):
    """文本块直接相连、thinking 进 reasoning_content、usage 原样保留。"""
    _, state = http_capture
    state["json"] = {
        **_ANTHROPIC_OK,
        "content": [
            {"type": "text", "text": "A"},
            {"type": "text", "text": "B"},
            {"type": "thinking", "thinking": "T"},
        ],
    }
    request = _native_request("anthropic", "claude-sonnet-4-5", "https://api.anthropic.com")
    response = await AnthropicNativeAdapter().complete(request)

    assert response.choices[0].message.content == "AB"
    assert response.choices[0].message.reasoning_content == "T"
    assert response.model == "claude-sonnet-4-5"
    usage = extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)


@pytest.mark.asyncio
async def test_gemini_response_normalization(http_capture):
    """文本块直接相连、usage 原样保留（字段名是 gemini 的原生名）。"""
    _, state = http_capture
    state["json"] = {
        **_GEMINI_OK,
        "candidates": [
            {"content": {"parts": [{"text": "A"}, {"text": "B"}], "role": "model"}, "finishReason": "STOP", "index": 0},
        ],
    }
    request = _native_request("gemini", "gemini-2.5-flash", "https://generativelanguage.googleapis.com/v1beta")
    response = await GeminiNativeAdapter().complete(request)

    assert response.choices[0].message.content == "AB"
    assert response.model == "gemini-2.5-flash"
    usage = extract_usage(response)
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)


def test_anthropic_cache_creation_split_is_merged():
    """Anthropic 新版把缓存写入拆成 5m / 1h 两个字段，要合并成总量。

    ``extract_usage`` 只认 ``cache_creation_input_tokens``（总量）；不合并
    的话缓存写入会漏计。新旧两种响应形状都可能给出缓存写入量，取较大者。
    """
    from app.services.llm.adapters.anthropic_native import normalize_usage

    usage = normalize_usage(
        {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation": {"ephemeral_5m_input_tokens": 20, "ephemeral_1h_input_tokens": 5},
        }
    )
    assert usage["cache_creation_input_tokens"] == 25


# ── 4. 计费口径 ────────────────────────────────────────────────────────────


def test_anthropic_pricing_uses_native_token_semantics():
    """anthropic 的 input 不含缓存，缓存读/写按各自的价单独算。

    Anthropic API 的原生口径：``input_tokens`` 不含缓存，缓存读/写是独立字段。
    本仓库 ``_input_tokens_include_cache`` 对 anthropic 走「不减缓存」分支，
    与之吻合——所以自研层给 Anthropic **原生** usage 时金额是对的。

    litellm 侧把三者合并成 OpenAI 形状的 ``prompt_tokens``（含缓存），在本仓库
    会与缓存价重复计费：那是 litellm 路径的既有问题，另开 issue。
    """
    from app.services.llm.adapters.anthropic_native import normalize_usage

    usage = extract_usage(
        SimpleNamespace(
            model="claude-sonnet-4-5",
            usage=normalize_usage(
                {
                    "input_tokens": 100,
                    "output_tokens": 50,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 20,
                }
            ),
        )
    )
    assert (usage.input_tokens, usage.output_tokens) == (100, 50)
    assert (usage.cache_read_tokens, usage.cache_creation_tokens) == (30, 20)

    costs = calculate_cost(
        usage,
        {"input": 1000.0, "output": 2000.0, "cache_hit": 100.0, "cache_create": 1250.0},
        provider="anthropic",
        request_model="anthropic/claude-sonnet-4-5",
    )
    assert costs.billable_input_tokens == 100
    assert costs.input_cost == pytest.approx(0.1)
    assert costs.cache_read_cost == pytest.approx(0.003)
    assert costs.cache_creation_cost == pytest.approx(0.025)


def test_gemini_prompt_tokens_include_cache():
    """gemini 的 ``promptTokenCount`` 含缓存，仓库的计价分支会减掉它。

    Google 文档口径：``promptTokenCount`` 含缓存，``cachedContentTokenCount``
    是其中的缓存部分。本仓库对非 anthropic provider 走「input 含缓存、要减」
    分支，减掉后即为不含缓存的输入。
    """
    usage = extract_usage(
        SimpleNamespace(
            model="gemini-2.5-flash",
            usage={"promptTokenCount": 100, "candidatesTokenCount": 50, "cachedContentTokenCount": 30},
        )
    )
    assert (usage.input_tokens, usage.output_tokens, usage.cache_read_tokens) == (100, 50, 30)

    costs = calculate_cost(
        usage,
        {"input": 1000.0, "output": 2000.0, "cache_hit": 100.0, "cache_create": None},
        provider="gemini",
        request_model="gemini/gemini-2.5-flash",
    )
    assert costs.billable_input_tokens == 70
    assert costs.input_cost == pytest.approx(0.07)


# ── 5. registry 分流 ───────────────────────────────────────────────────────


def test_native_protocol_routing():
    """anthropic / gemini 走自有实现；未实现的协议显式回落。"""
    assert resolve_protocol(_model("anthropic")) == "anthropic_native"
    assert resolve_protocol(_model("gemini")) == "gemini_native"
    assert resolve_protocol(_model("custom")) == "openai_compat"
    for provider in ("vertex_ai", "azure", "bedrock"):
        assert resolve_protocol(_model(provider)) is None
        reason = native_unavailable_reason(_model(provider, api_base="https://x.example.com"))
        assert reason is not None
        assert provider in reason


def test_anthropic_and_gemini_need_no_api_base():
    """两家都有与 litellm 一致的默认网关，缺 api_base 也能走自有路径。"""
    assert native_unavailable_reason(_model("anthropic")) is None
    assert native_unavailable_reason(_model("gemini")) is None


def test_gemini_json_schema_is_unsupported():
    """gemini 只复刻 json_object；其它 response_format 形状显式拒绝。"""
    model = _model("gemini", "gemini-2.5-flash")
    assert native_unavailable_reason(model, {"type": "json_object"}) is None
    reason = native_unavailable_reason(model, {"type": "json_schema", "json_schema": {"name": "x"}})
    assert reason is not None
    assert "json_object" in reason


@pytest.mark.asyncio
async def test_native_transport_dispatch_per_protocol(monkeypatch, http_capture):
    """native 模式下按协议分派到对应适配器。"""
    _, state = http_capture
    state["json"] = _ANTHROPIC_OK

    content = await _call_engine._call_llm_single(
        messages=_MESSAGES,
        model="anthropic/claude-sonnet-4-5",
        api_key="test-key",
        api_base=None,
        temperature=0.3,
        max_tokens=200,
        response_format=None,
        model_config=_model("anthropic"),
    )
    assert content == "hello"


@pytest.mark.asyncio
async def test_gemini_dispatch_uses_default_gateway(monkeypatch, http_capture):
    """gemini 缺 api_base 时走默认网关，且落到 gemini 适配器上。"""
    captured, state = http_capture
    state["json"] = _GEMINI_OK

    content = await _call_engine._call_llm_single(
        messages=_MESSAGES,
        model="gemini/gemini-2.5-flash",
        api_key="test-key",
        api_base=None,
        temperature=0.3,
        max_tokens=200,
        response_format=None,
        model_config=_model("gemini", "gemini-2.5-flash"),
    )
    assert content == "hello"
    assert (
        captured[-1]["url"]
        == "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert captured[-1]["headers"].get("x-goog-api-key") == "test-key"


def test_unsupported_protocol_raises_configuration_error(monkeypatch):
    """没有自有实现的 provider 显式报配置错误，而不是静默换路。"""
    import asyncio

    from app.services.llm.adapters.errors import LlmConfigurationError

    with pytest.raises(LlmConfigurationError, match="vertex_ai"):
        asyncio.run(
            _call_engine._call_llm_single(
                messages=_MESSAGES,
                model="vertex_ai/gemini-2.5-flash",
                api_key="test-key",
                api_base="https://x.example.com",
                temperature=0.3,
                max_tokens=200,
                response_format=None,
                model_config=_model("vertex_ai", api_base="https://x.example.com"),
            )
        )
