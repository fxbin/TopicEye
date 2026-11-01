"""anthropic 原生协议的自有传输实现（``/v1/messages``）。

与 OpenAI 兼容族的差别是**协议本身**的差别，不是风格差别：

- 端点是 ``{api_base}/v1/messages``，鉴权走 ``x-api-key`` + ``anthropic-version``
  头（不是 ``Authorization: Bearer``）。
- 请求体不是 OpenAI 形状：system 消息抽到顶层 ``system``，其余消息的
  ``content`` 是 ``[{"type": "text", "text": ...}]`` 块数组。
- 响应的文本在 ``content[]`` 块里，usage 是 Anthropic 原生字段名。

与 litellm 的行为对齐点（实测 litellm 1.103.1 + httpx mock 抓真实请求）：

- **URL 拼接**：``api_base`` 去掉尾部斜杠后拼 ``/v1/messages``；已含
  ``/v1/messages`` 则原样（litellm 同规则，含 ``api_base`` 以 ``/v1`` 结尾时
  会拼成 ``/v1/v1/messages``——litellm 的怪癖，照抄）。
- **请求体**：``{"model", "messages", "max_tokens", "temperature", "system"}``，
  多条 system 消息逐条成块（``[{"type":"text",...}, ...]``）。
- **response_format**：litellm 对 anthropic **静默丢弃**该参数（实测请求体里
  没有），自家路径照做——不静默丢弃 litellm 丢弃的东西，否则两条路径的
  行为就不一样了。
- **用量**：给 Anthropic **原生** usage（``input_tokens`` 不含缓存，缓存读/写
  是各自独立的字段——这是 Anthropic API 的原生口径）。本仓库
  ``_input_tokens_include_cache`` 对 anthropic 的分支（input 不含缓存、不减）
  正好对上这个形状。litellm 侧把三者合并成 OpenAI 形状的 ``prompt_tokens``
  （含缓存），在本仓库会与缓存价重复计费——那是 litellm 路径的既有问题，
  另开 issue，不在本次范围内。

不做的事：不流式、不带 tools、不做 vision/多模态。
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
    classify_anthropic_error,
)

logger = logging.getLogger(__name__)

_MESSAGES_ENDPOINT = "/v1/messages"

# Anthropic 要求带 API 版本头；litellm 发的是这个值（实测）。
ANTHROPIC_API_VERSION = "2023-06-01"


def build_messages_url(base_url: str) -> str:
    """按 litellm 的规则拼出 ``/v1/messages`` 端点。"""
    base = (base_url or "").rstrip("/")
    if base.endswith(_MESSAGES_ENDPOINT):
        return base
    return f"{base}{_MESSAGES_ENDPOINT}"


def _text_of(content: Any) -> str:
    """取消息正文。仓库只发字符串内容，其余形状按字符串化处理。"""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def build_request_body(request: NativeRequest) -> dict[str, Any]:
    """把 OpenAI 形状的消息映射成 anthropic ``/v1/messages`` 的请求体。

    实测 litellm 1.103.1 发出的形状：

    .. code-block:: json

        {"model": "...",
         "messages": [{"role": "user", "content": [{"type": "text", "text": "..."}]}],
         "max_tokens": 200, "temperature": 0.3,
         "system": [{"type": "text", "text": "..."}]}
    """
    system_blocks: list[dict[str, str]] = []
    messages: list[dict[str, Any]] = []

    for message in request.messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        text = _text_of(message.get("content"))
        if role == "system":
            system_blocks.append({"type": "text", "text": text})
            continue
        if role not in ("user", "assistant"):
            # litellm 把 system 之外的非已知角色按 user 发（实测 "developer"
            # 被并进 system）。这里只把非 system 的未知角色并入 user，并记
            # warning——静默改写角色会丢掉语义。
            logger.warning("Anthropic native transport: unsupported role %r sent as user", role)
        messages.append(
            {"role": "assistant" if role == "assistant" else "user", "content": [{"type": "text", "text": text}]}
        )

    body: dict[str, Any] = {"model": request.model, "messages": messages}
    if request.max_tokens is not None:
        body["max_tokens"] = request.max_tokens
    if request.temperature is not None:
        body["temperature"] = request.temperature
    if system_blocks:
        body["system"] = system_blocks
    return body


def build_headers(request: NativeRequest) -> dict[str, str]:
    """鉴权与版本头（litellm 同形状）。"""
    headers = {"Content-Type": "application/json", "anthropic-version": ANTHROPIC_API_VERSION}
    if request.api_key:
        headers["x-api-key"] = request.api_key
    headers.update(request.headers)
    return headers


def normalize_usage(raw: Any) -> dict[str, Any] | None:
    """把 anthropic 的 usage 归一化成 ``extract_usage`` 读得懂的形状。

    Anthropic 新版把缓存写入拆成 ``cache_creation.ephemeral_5m_input_tokens``
    与 ``ephemeral_1h_input_tokens`` 两个字段，而 ``extract_usage`` 只认
    ``cache_creation_input_tokens``（总量）。这里取两者的和与声明值的较大者
    ——新旧两种响应形状都可能给出缓存写入量，取较大者才不会漏计。
    """
    if not isinstance(raw, dict):
        return None
    usage = dict(raw)
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        total = 0
        for key in ("ephemeral_5m_input_tokens", "ephemeral_1h_input_tokens"):
            value = creation.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                total += value
        declared = usage.get("cache_creation_input_tokens")
        if isinstance(declared, int) and not isinstance(declared, bool):
            total = max(total, declared)
        if total:
            usage["cache_creation_input_tokens"] = total
    return usage


def _normalize_response(payload: dict[str, Any]) -> AdapterResponse:
    """把 anthropic 响应体归一化成 :class:`AdapterResponse`。

    文本块按出现顺序直接相连（litellm 同形状：两块 ``"A"``/``"B"`` 得到
    ``"AB"``）。``thinking`` 块进 ``reasoning_content``。
    """
    blocks = payload.get("content")
    texts: list[str] = []
    reasoning: list[str] = []
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                texts.append(str(block.get("text") or ""))
            elif block_type == "thinking":
                reasoning.append(str(block.get("thinking") or ""))

    if not texts and not reasoning:
        raise LlmServerError(
            f"Anthropic response has no content: {str(payload)[:500]}",
            status_code=200,
            body=str(payload)[:2000],
        )

    model = payload.get("model")
    return AdapterResponse(
        choices=[
            AdapterChoice(
                message=AdapterMessage(
                    content="".join(texts) if texts else None,
                    reasoning_content="".join(reasoning) if reasoning else None,
                ),
                index=0,
                finish_reason=payload.get("stop_reason"),
            )
        ],
        usage=normalize_usage(payload.get("usage")),
        model=str(model) if model else None,
    )


class AnthropicNativeAdapter:
    """anthropic ``/v1/messages`` 协议的自有传输实现。"""

    name = "anthropic_native"

    async def complete(self, request: NativeRequest) -> AdapterResponse:
        url = build_messages_url(request.base_url)
        body = build_request_body(request)
        headers = build_headers(request)

        try:
            async with httpx.AsyncClient(timeout=request.timeout) as client:
                response = await client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise LlmTransportError(f"LLM request timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise LlmTransportError(f"LLM request failed: {exc}") from exc

        if response.status_code >= 400:
            error_body = (response.text or "").strip()[:2000]
            error = classify_anthropic_error(response.status_code, error_body)
            logger.warning(
                "Native LLM transport error: url=%s model=%s status=%s kind=%s message=%s",
                url,
                request.model,
                response.status_code,
                type(error).__name__,
                error_body[:500],
            )
            raise error

        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise LlmTransportError(f"LLM response is not valid JSON: {exc}") from exc

        if not isinstance(payload, dict):
            raise LlmTransportError("LLM response is not a JSON object")

        return _normalize_response(payload)
