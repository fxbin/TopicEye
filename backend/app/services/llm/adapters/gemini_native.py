"""google gemini 原生协议的自有传输实现（``generateContent``）。

gemini 的协议与 OpenAI 兼容族、anthropic 都不同：

- 端点是 ``{api_base}/models/{model}:generateContent``，鉴权走
  ``x-goog-api-key`` 头（不是 ``Authorization: Bearer``）。
- 请求体是 ``contents`` / ``system_instruction`` / ``generationConfig``，
  assistant 的角色名是 ``model``（不是 ``assistant``）。
- 响应的文本在 ``candidates[].content.parts[]`` 里，usage 是
  ``usageMetadata``（``promptTokenCount`` 等）。

与 litellm 的行为对齐点（实测 litellm 1.103.1 + httpx mock 抓真实请求）：

- **URL 拼接**：``{api_base}/models/{model}:generateContent``，直接拼，不去重
  尾段（litellm 同规则）。
- **请求体字段名用 snake_case**：``max_output_tokens`` / ``response_mime_type``
  / ``system_instruction``。proto3 的 JSON 映射同时接受 camelCase 与原名
  （snake_case），所以这不是笔误，litellm 一直这么发。
- **response_format**：``{"type": "json_object"}`` 映射成
  ``generationConfig.response_mime_type = "application/json"``。其它形状
  （json_schema 等）**不在自有路径复刻**——由 registry 显式回落 litellm。
- **用量**：给 gemini 原生 ``usageMetadata``。``promptTokenCount`` 是**含缓存**
  的输入总量，``cachedContentTokenCount`` 是其中的缓存部分（Google 文档口径），
  本仓库 ``_input_tokens_include_cache`` 对非 anthropic provider 的分支会
  减掉缓存，两边金额一致。

不做的事：不流式、不带 tools、不做文件/搜索工具、不做 vertex_ai 托管端点
（认证与端点都不同，另开 issue）。
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
    classify_gemini_error,
)

logger = logging.getLogger(__name__)

_GENERATE_CONTENT_SUFFIX = ":generateContent"

# gemini 的角色名：assistant 在 Gemini 协议里叫 model。
_ROLE_MODEL = "model"
_ROLE_USER = "user"


def build_generate_content_url(base_url: str, model: str) -> str:
    """按 litellm 的规则拼出 generateContent 端点。"""
    base = (base_url or "").rstrip("/")
    return f"{base}/models/{model}{_GENERATE_CONTENT_SUFFIX}"


def _text_of(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return str(content)


def build_request_body(request: NativeRequest) -> dict[str, Any]:
    """把 OpenAI 形状的消息映射成 gemini ``generateContent`` 的请求体。

    实测 litellm 1.103.1 发出的形状：

    .. code-block:: json

        {"contents": [{"role": "user", "parts": [{"text": "..."}]}],
         "system_instruction": {"parts": [{"text": "..."}]},
         "generationConfig": {"temperature": 0.3, "max_output_tokens": 200}}
    """
    system_parts: list[dict[str, str]] = []
    contents: list[dict[str, Any]] = []

    for message in request.messages or []:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        text = _text_of(message.get("content"))
        if role == "system":
            system_parts.append({"text": text})
            continue
        if role not in (_ROLE_USER, "assistant"):
            logger.warning("Gemini native transport: unsupported role %r sent as user", role)
        contents.append({"role": _ROLE_MODEL if role == "assistant" else _ROLE_USER, "parts": [{"text": text}]})

    body: dict[str, Any] = {"contents": contents}

    generation_config: dict[str, Any] = {}
    if request.temperature is not None:
        generation_config["temperature"] = request.temperature
    if request.max_tokens is not None:
        generation_config["max_output_tokens"] = request.max_tokens
    if request.response_format and request.response_format.get("type") == "json_object":
        generation_config["response_mime_type"] = "application/json"
    if generation_config:
        body["generationConfig"] = generation_config

    if system_parts:
        body["system_instruction"] = {"parts": system_parts}
    return body


def build_headers(request: NativeRequest) -> dict[str, str]:
    """鉴权头（litellm 同形状）。"""
    headers = {"Content-Type": "application/json"}
    if request.api_key:
        headers["x-goog-api-key"] = request.api_key
    headers.update(request.headers)
    return headers


def _normalize_response(payload: dict[str, Any]) -> AdapterResponse:
    """把 gemini 响应体归一化成 :class:`AdapterResponse`。

    文本块按出现顺序直接相连（litellm 同形状）。usage 原样保留
    ``usageMetadata`` 的字段名——``extract_usage`` 本来就认
    ``promptTokenCount`` / ``candidatesTokenCount`` / ``cachedContentTokenCount``。
    """
    candidates = payload.get("candidates")
    choices: list[AdapterChoice] = []
    if isinstance(candidates, list):
        for index, candidate in enumerate(candidates):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            parts = content.get("parts") if isinstance(content, dict) else None
            texts: list[str] = []
            if isinstance(parts, list):
                for part in parts:
                    if isinstance(part, dict) and part.get("text") is not None:
                        texts.append(str(part.get("text") or ""))
            choices.append(
                AdapterChoice(
                    message=AdapterMessage(content="".join(texts) if texts else None),
                    index=index,
                    finish_reason=candidate.get("finishReason"),
                )
            )

    if not choices:
        raise LlmServerError(
            f"Gemini response has no candidates: {str(payload)[:500]}",
            status_code=200,
            body=str(payload)[:2000],
        )

    usage = payload.get("usageMetadata")
    model = payload.get("modelVersion")
    return AdapterResponse(
        choices=choices,
        usage=usage if isinstance(usage, dict) else None,
        model=str(model) if model else None,
    )


class GeminiNativeAdapter:
    """google gemini ``generateContent`` 协议的自有传输实现。"""

    name = "gemini_native"

    async def complete(self, request: NativeRequest) -> AdapterResponse:
        url = build_generate_content_url(request.base_url, request.model)
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
            error = classify_gemini_error(response.status_code, error_body)
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
