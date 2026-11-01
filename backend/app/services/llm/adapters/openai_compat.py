"""
OpenAI 兼容协议的自有传输实现。

用 httpx 直连 ``POST {base_url}/chat/completions``，请求体与响应体都按
OpenAI 兼容协议处理（国产厂商与聚合网关的 ``/v1/chat/completions`` 都是
这个形状）。这是本仓库最主流的一类 provider——线上 17758 次调用全部落在
``custom`` provider 的 OpenAI 兼容网关上。

与 litellm 的行为对齐点（实测 litellm 1.103.1 + httpx mock 复现）：

- **URL 拼接**：``base_url`` 去掉尾部斜杠后拼 ``/chat/completions``；若
  ``base_url`` 已含 ``chat/completions`` 则原样使用（litellm
  ``get_complete_url`` 同规则）。
- **鉴权**：``Authorization: Bearer {api_key}``。
- **请求体**：``model`` / ``messages`` / ``temperature`` / ``max_tokens`` /
  ``response_format``（仅在传入时）。litellm 对 OpenAI 兼容族发的就是这几个
  字段，不额外注入 ``stream`` 等。
- **无内部重试**：litellm 侧靠 ``num_retries=0`` 关掉内部重试，这里天然
  没有内部重试，重试仍由编排层的 tenacity 统一管理（同一语义）。
- **超时**：由调用方传入，同时落到 httpx 的 timeout。

不做的事：不流式、不带 tools、不做 embedding、不做多模态。
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.services.llm.adapters.base import AdapterChoice, AdapterMessage, AdapterResponse, NativeRequest
from app.services.llm.adapters.errors import (
    LlmServerError,
    LlmTransportError,
    LlmUnsupportedParamsError,
    classify_status_error,
)
from app.services.llm.adapters.http_pool import get_pooled_client

logger = logging.getLogger(__name__)

_CHAT_COMPLETIONS_ENDPOINT = "chat/completions"

# 不支持 ``response_format`` 的模型。litellm 在客户端预检这一步就抛
# ``UnsupportedParamsError``（不发请求），编排层据此去掉该参数重试。
# 口径与 litellm 的 OpenAI 兼容族参数表一致：这两个模型不在其
# ``response_format`` 支持列表里。
_MODELS_WITHOUT_RESPONSE_FORMAT = frozenset({"gpt-4", "gpt-3.5-turbo-16k"})


def supports_response_format(model: str) -> bool:
    """该模型是否支持 ``response_format``（与 litellm 的预检口径一致）。"""
    return model not in _MODELS_WITHOUT_RESPONSE_FORMAT


def build_chat_completions_url(base_url: str) -> str:
    """按 litellm 的 OpenAI 兼容规则拼出完整 endpoint。"""
    base = (base_url or "").rstrip("/")
    if _CHAT_COMPLETIONS_ENDPOINT in base:
        return base
    return f"{base}/{_CHAT_COMPLETIONS_ENDPOINT}"


def _extract_error_body(response: httpx.Response) -> str:
    """取 provider 的**原始响应体**，用于错误分类。

    litellm 侧参与判定的是 openai SDK 异常的 ``str(exc)``，里面包含整个
    响应体——特征串常出现在 ``type``/``code`` 等字段（如 GLM 的
    ``"type": "content_filter"``），只看 ``error.message`` 会漏判。
    """
    text = (response.text or "").strip()
    if not text:
        return f"HTTP {response.status_code}"
    return text[:2000]


def _extract_error_message(response: httpx.Response) -> str:
    """从错误响应体里取出可读信息（用于日志展示）。"""
    try:
        payload = response.json()
    except (json.JSONDecodeError, ValueError):
        return _extract_error_body(response)

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("detail") or error.get("code")
            if message:
                return str(message)[:2000]
        if isinstance(error, str) and error:
            return error[:2000]
        message = payload.get("message") or payload.get("detail")
        if message:
            return str(message)[:2000]
    return _extract_error_body(response)


def _normalize_usage(raw: Any) -> dict[str, Any] | None:
    """把 provider 返回的 usage 收敛成 dict（None 表示 provider 未返回）。"""
    if not isinstance(raw, dict):
        return None
    return raw


def _normalize_response(payload: dict[str, Any]) -> AdapterResponse:
    """把 OpenAI 兼容响应体归一化成 :class:`AdapterResponse`。

    响应体里没有可用候选时**抛错而不是返回空壳**——否则调用方取
    ``choices[0]`` 会炸出 IndexError，错误分类与落库都拿不到有意义的信息。
    编排层的判定与 litellm 一致：这类错误可重试、且属 provider 侧问题。
    """
    raw_choices = payload.get("choices")
    if not isinstance(raw_choices, list) or not raw_choices:
        raise LlmServerError(
            f"LLM response has no choices: {str(payload)[:500]}",
            status_code=200,
            body=str(payload)[:2000],
        )

    choices: list[AdapterChoice] = []
    for index, raw_choice in enumerate(raw_choices):
        if not isinstance(raw_choice, dict):
            continue
        raw_message = raw_choice.get("message")
        if not isinstance(raw_message, dict):
            raw_message = {}
        choices.append(
            AdapterChoice(
                message=AdapterMessage(
                    content=raw_message.get("content"),
                    reasoning_content=raw_message.get("reasoning_content"),
                ),
                index=index,
                finish_reason=raw_choice.get("finish_reason"),
            )
        )

    model = payload.get("model")
    return AdapterResponse(
        choices=choices,
        usage=_normalize_usage(payload.get("usage")),
        model=str(model) if model else None,
    )


class OpenAICompatAdapter:
    """OpenAI 兼容协议的自有传输实现。"""

    name = "openai_compat"

    async def complete(self, request: NativeRequest) -> AdapterResponse:
        url = build_chat_completions_url(request.base_url)

        # 客户端预检：模型不支持 response_format 时按 litellm 的口径直接拒绝，
        # 让编排层的「去掉该参数重试」分支生效（而不是发出去吃一个 400）。
        if request.response_format is not None and not supports_response_format(request.model):
            raise LlmUnsupportedParamsError(
                f"Setting response_format is not supported by {request.model}",
                status_code=400,
            )

        body: dict[str, Any] = {
            "model": request.model,
            "messages": request.messages,
        }
        if request.temperature is not None:
            body["temperature"] = request.temperature
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens
        if request.response_format is not None:
            body["response_format"] = request.response_format

        headers = {"Content-Type": "application/json"}
        if request.api_key:
            headers["Authorization"] = f"Bearer {request.api_key}"
        headers.update(request.headers)

        try:
            response = await get_pooled_client().post(url, json=body, headers=headers, timeout=request.timeout)
        except httpx.TimeoutException as exc:
            raise LlmTransportError(f"LLM request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LlmTransportError(f"LLM request failed: {exc}") from exc

        if response.status_code >= 400:
            error_body = _extract_error_body(response)
            error = classify_status_error(response.status_code, error_body)
            logger.warning(
                "Native LLM transport error: url=%s model=%s status=%s kind=%s message=%s",
                url,
                request.model,
                response.status_code,
                type(error).__name__,
                _extract_error_message(response)[:500],
            )
            raise error

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LlmTransportError(f"LLM response is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise LlmTransportError("LLM response is not a JSON object")

        return _normalize_response(payload)
