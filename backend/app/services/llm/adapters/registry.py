"""
传输实现选择与路由解析。

回答两个问题：

1. **这个模型能不能走自有传输层？**——按**协议**判定，不按某个厂商名单
   硬编码。已实现的协议：OpenAI ``/chat/completions``、anthropic
   ``/v1/messages``、gemini ``generateContent``；azure / bedrock / vertex_ai
   的认证与端点形状不同，尚无实现（#190），这类配置显式报
   ``LlmConfigurationError``，不静默换路。
2. **自有传输层要往哪个 URL ���、用哪个模型名？**

   - **URL**：``api_base`` 优先用编排层解析好的（已含容器回环地址重写）；
     没配置时用 provider 的默认网关（``DEFAULT_API_BASES``，与
     ``model_catalog_service`` 的精选目录保持一致，有测试守卫）。
   - **模型名**：线上真正识别的**裸模型名**。``custom`` + ``minicpm5-2b``
     发的是 ``minicpm5-2b``，``openai`` + ``example-org/example-29b`` 发的是
     ``example-org/example-29b``（斜杠后的组织/模型命名原样保留，#83）。

**为什么按协议分流？** provider 列里存的是沿用自 litellm 时代的 provider 名
（历史数据如此，不改名），而厂商名单会变；自有传输层只依赖「协议 + 端点」。

**显式路由串与 litellm 专属参数不参与自有路径**：``litellm_model`` /
``litellm_params.model`` 是 litellm 的路由串约定；``api_version`` /
``custom_llm_provider`` / ``drop_params`` 会改变协议或路由语义。遇到这些
显式报错，提示改用 provider 列与 api_base，不在自有路径里猜测它们的意思。
配置键名保留 ``litellm_params`` 等历史写法：它们已落库在用户的模型配置里。
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.llm.adapters.anthropic_native import AnthropicNativeAdapter
from app.services.llm.adapters.base import NativeRequest
from app.services.llm.adapters.gemini_native import GeminiNativeAdapter
from app.services.llm.adapters.openai_compat import OpenAICompatAdapter

logger = logging.getLogger(__name__)

# 走 OpenAI ``/chat/completions`` 协议的 provider。
# 不含 anthropic / gemini / azure / bedrock / vertex_ai —— 协议不同。
OPENAI_COMPATIBLE_PROVIDERS: frozenset[str] = frozenset(
    {
        "openai",
        "custom",
        "deepseek",
        "zhipu",
        "minimax",
        "moonshot",
        "xai",
        "mistral",
        "openrouter",
    }
)

# 原生协议族：请求体、响应体、错误分类都另有一套。
ANTHROPIC_PROVIDERS: frozenset[str] = frozenset({"anthropic"})
GEMINI_PROVIDERS: frozenset[str] = frozenset({"gemini"})

# provider → 协议实现。按**协议**分流。
PROTOCOL_BY_PROVIDER: dict[str, str] = {
    **{provider: "openai_compat" for provider in OPENAI_COMPATIBLE_PROVIDERS},
    **{provider: "anthropic_native" for provider in ANTHROPIC_PROVIDERS},
    **{provider: "gemini_native" for provider in GEMINI_PROVIDERS},
}

# provider 未显式配置 api_base 时的默认网关。
#
# 与 ``model_catalog_service.FEATURED_PROVIDERS`` 的精选默认值保持一致
# （deepseek / zhipu / minimax / moonshot / openrouter 有镜像测试守卫）；
# 目录里没给默认值的厂商（anthropic / gemini / xai / mistral）写官方端点，
# 连同 openai 一起由显式断言钉住，防误改。``custom`` 刻意不在这里——
# 「完全自定义」必须由用户自带 api_base。
DEFAULT_API_BASES: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "anthropic": "https://api.anthropic.com",
    # 生成式语言 API 的 v1beta。
    "gemini": "https://generativelanguage.googleapis.com/v1beta",
    "deepseek": "https://api.deepseek.com",
    "zhipu": "https://open.bigmodel.cn/api/paas/v4/",
    "minimax": "https://api.minimaxi.com/v1",
    "moonshot": "https://api.moonshot.cn/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "xai": "https://api.x.ai/v1",
    "mistral": "https://api.mistral.ai/v1",
}

# ``extra_params.litellm_params`` 里自有路径认的键：只影响请求头与请求体字段。
# ``timeout`` 由编排层统一处理（见 _call_engine）；``num_retries`` 已无意义
# （传输层没有内部重试，重试全在编排层），保留在名单里只是为了不让存量
# 配置因为多了这个键而报错。
NATIVE_HONORED_LITELLM_PARAMS: frozenset[str] = frozenset(
    {
        "default_headers",
        "extra_headers",
        "organization",
        "metadata",
        "timeout",
        "num_retries",
    }
)

# 已经提示过「无法承接」的 provider——同一个 provider + 原因只提示一次，避免刷屏。
_warned_unsupported: set[str] = set()


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def resolve_provider(model_config: Any) -> str | None:
    """取模型实际使用的 provider（litellm provider 名）。

    与 `model_resolver.resolve_litellm_model` 的取值优先级一致：
    ``extra_params.litellm_provider`` → ``litellm_params.custom_llm_provider``
    → 模型自身的 ``provider`` 列。
    """
    extra = getattr(model_config, "extra_params", None)
    params = extra if isinstance(extra, dict) else {}
    litellm_params = params.get("litellm_params") if isinstance(params.get("litellm_params"), dict) else {}

    provider = _clean(params.get("litellm_provider")) or _clean(litellm_params.get("custom_llm_provider"))
    return provider or _clean(getattr(model_config, "provider", None))


def resolve_wire_model(model_id: str, provider: str | None) -> str:
    """算出发给 provider 的裸模型名（不含 provider 前缀）。

    与 litellm 逐条对齐（litellm 收到 ``provider/model`` 路由串后剥掉第一段）：

    - ``custom``：仓库的路由串恒为 ``openai/{model_id}``，litellm 剥掉
      ``openai/`` 后正好是 model_id 本身 → 原样返回。
    - 其它 provider：model_id 已带 ``{provider}/`` 前缀时，litellm 剥掉那一段
      → 剥掉；否则路由串是 ``{provider}/{model_id}``，剥完仍是 model_id
      → 原样返回。
    """
    if not model_id:
        return model_id
    if not provider or provider == "custom":
        return model_id
    prefix = f"{provider}/"
    if model_id.startswith(prefix):
        return model_id[len(prefix) :]
    return model_id


def _extra_params(model_config: Any) -> dict[str, Any]:
    extra = getattr(model_config, "extra_params", None)
    return extra if isinstance(extra, dict) else {}


def native_unavailable_reason(model_config: Any, response_format: dict | None = None) -> str | None:
    """该模型不能走自有传输层的原因；可走时返回 None。

    判定项：

    1. provider 属已支持的协议族（OpenAI 兼容 / anthropic / gemini，按协议判）
    2. 模型有裸模型名
    3. 能解析出 api_base（模型自带，或 provider 有默认网关）
    4. 没配 litellm 专属的显式路由串
    5. litellm_params 里没有会改变协议/路由语义的键
    6. 该协议能如实复刻 ``response_format``（gemini 只复刻 json_object）
    """
    provider = resolve_provider(model_config)
    if not provider:
        return "模型未配置 provider"
    protocol = PROTOCOL_BY_PROVIDER.get(provider.lower())
    if protocol is None:
        return f"provider {provider} 没有自有协议实现（azure / bedrock / vertex_ai 见 #190）"

    model_id = _clean(getattr(model_config, "model_id", None))
    if not model_id:
        return "模型未配置 model_id"

    params = _extra_params(model_config)
    litellm_params = params.get("litellm_params") if isinstance(params.get("litellm_params"), dict) else {}

    if _clean(params.get("litellm_model")) or _clean(litellm_params.get("model")):
        return "配置了 litellm 专属的显式路由串，请改用 provider 列 + model_id"

    unsupported = sorted(set(litellm_params) - NATIVE_HONORED_LITELLM_PARAMS)
    if unsupported:
        return f"litellm_params 含自有传输层不支持的参数: {', '.join(unsupported)}"

    if not resolve_base_url(model_config, provider):
        return f"provider {provider} 未配置 api_base 且无默认网关"

    # gemini 侧只复刻 json_object；其它形状没有对应的请求字段。
    if protocol == "gemini_native" and response_format is not None and response_format.get("type") != "json_object":
        return "gemini 只支持 response_format=json_object"

    return None


def resolve_protocol(model_config: Any) -> str | None:
    """该模型对应的协议实现名；不支持时返回 None。"""
    provider = resolve_provider(model_config)
    if not provider:
        return None
    return PROTOCOL_BY_PROVIDER.get(provider.lower())


def resolve_base_url(model_config: Any, provider: str | None) -> str | None:
    """解析自有传输层要用的 api_base（模型自带优先）。"""
    configured = _clean(getattr(model_config, "api_base", None))
    if configured:
        return configured
    if provider:
        return DEFAULT_API_BASES.get(provider)
    return None


def supports_native_transport(model_config: Any) -> bool:
    """该模型是否可走自有传输层。"""
    return native_unavailable_reason(model_config) is None


def build_native_request(
    model_config: Any,
    *,
    messages: list,
    api_key: str | None,
    api_base: str | None,
    temperature: float | None,
    max_tokens: int | None,
    response_format: dict | None,
    timeout: float,
) -> NativeRequest | None:
    """构造自有传输层的请求；配置不完整时返回 None（调用方据此报配置错误）。

    ``api_base`` 传编排层已解析好的值（含容器回环地址重写）。
    """
    provider = resolve_provider(model_config)
    if not provider:
        return None

    model_id = _clean(getattr(model_config, "model_id", None)) or ""
    if not model_id:
        return None

    base_url = api_base or resolve_base_url(model_config, provider)
    if not base_url:
        return None

    params = _extra_params(model_config)
    litellm_params = params.get("litellm_params") if isinstance(params.get("litellm_params"), dict) else {}

    headers: dict[str, str] = {}
    for key in ("default_headers", "extra_headers"):
        value = litellm_params.get(key)
        if isinstance(value, dict):
            headers.update({str(k): str(v) for k, v in value.items()})
    organization = _clean(litellm_params.get("organization"))
    if organization:
        headers["OpenAI-Organization"] = organization

    return NativeRequest(
        model=resolve_wire_model(model_id, provider),
        base_url=base_url,
        api_key=api_key,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        response_format=response_format,
        timeout=timeout,
        headers=headers,
    )


def note_unsupported(provider: str | None, reason: str) -> None:
    """记录一次「自有传输层无法承接该配置」——同一个 provider+原因只提示一次。

    调用方随后会抛 ``LlmConfigurationError``；这里的 warning 是给运维看日志用的：
    异常可能被 failover 吞掉换下一个候选，日志里仍要留下这个配置有问题的痕迹。
    """
    key = f"{provider or 'unknown'}:{reason}"
    if key in _warned_unsupported:
        return
    _warned_unsupported.add(key)
    logger.warning(
        "Native LLM transport cannot serve provider=%s (%s); candidate skipped",
        provider or "unknown",
        reason,
    )


# 单例：适配器无状态，URL 与请求体都在请求里。
_openai_compat_adapter = OpenAICompatAdapter()
_anthropic_native_adapter = AnthropicNativeAdapter()
_gemini_native_adapter = GeminiNativeAdapter()

_ADAPTERS_BY_PROTOCOL: dict[str, Any] = {
    "openai_compat": _openai_compat_adapter,
    "anthropic_native": _anthropic_native_adapter,
    "gemini_native": _gemini_native_adapter,
}


def get_openai_compat_adapter() -> OpenAICompatAdapter:
    return _openai_compat_adapter


def get_adapter(protocol: str):
    """按协议实现名取适配器单例。"""
    return _ADAPTERS_BY_PROTOCOL.get(protocol)
