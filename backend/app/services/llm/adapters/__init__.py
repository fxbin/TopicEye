"""
自有传输层（issue #181）。

编排层（failover / 冷却 / 熔断 / 限流 / 预算 / 缓存 / 计价）仍是本仓库
自己的代码；本包只负责「把请求发出去、把响应与错误归一化」这一层。

默认仍走 litellm（``LLM_TRANSPORT=litellm``）；切成 ``native`` 后，
OpenAI 兼容族走自有实现，其余 provider 显式回落 litellm 并记 warning。
"""

from __future__ import annotations

from app.services.llm.adapters.base import (
    AdapterChoice,
    AdapterMessage,
    AdapterResponse,
    LlmAdapter,
    NativeRequest,
)
from app.services.llm.adapters.errors import (
    LlmAdapterError,
    LlmAuthenticationError,
    LlmBadRequestError,
    LlmContentPolicyError,
    LlmContextWindowError,
    LlmNotFoundError,
    LlmRateLimitError,
    LlmServerError,
    LlmTimeoutError,
    LlmTransportError,
    LlmUnsupportedParamsError,
    classify_status_error,
    to_litellm_exception,
)
from app.services.llm.adapters.openai_compat import OpenAICompatAdapter, build_chat_completions_url
from app.services.llm.adapters.registry import (
    DEFAULT_API_BASES,
    OPENAI_COMPATIBLE_PROVIDERS,
    build_native_request,
    get_openai_compat_adapter,
    native_unavailable_reason,
    note_fallback,
    resolve_base_url,
    resolve_provider,
    resolve_wire_model,
    supports_native_transport,
)

__all__ = [
    "DEFAULT_API_BASES",
    "OPENAI_COMPATIBLE_PROVIDERS",
    "AdapterChoice",
    "AdapterMessage",
    "AdapterResponse",
    "LlmAdapter",
    "LlmAdapterError",
    "LlmAuthenticationError",
    "LlmBadRequestError",
    "LlmContentPolicyError",
    "LlmContextWindowError",
    "LlmNotFoundError",
    "LlmRateLimitError",
    "LlmServerError",
    "LlmTimeoutError",
    "LlmTransportError",
    "LlmUnsupportedParamsError",
    "NativeRequest",
    "OpenAICompatAdapter",
    "build_chat_completions_url",
    "build_native_request",
    "classify_status_error",
    "get_openai_compat_adapter",
    "native_unavailable_reason",
    "note_fallback",
    "resolve_base_url",
    "resolve_provider",
    "resolve_wire_model",
    "supports_native_transport",
    "to_litellm_exception",
]
