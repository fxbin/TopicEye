"""
自有传输层的数据契约。

编排层（`_call_engine` / `provider`）消费的是**归一化响应**，不是各家
provider 的原始响应。归一化对象刻意保持 litellm ``ModelResponse`` 的读取
形状（``.choices[0].message.content`` / ``.usage`` / ``.model``），这样
``llm_usage.extract_usage`` 与 ``has_complete_usage`` 的 ``_get_value``
读取（dict 与属性两种路径都支持）无需改动即可复用，用量与计价口径不因
更换传输实现而漂移。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class AdapterMessage:
    """归一化后的单条消息。"""

    content: str | None = None
    reasoning_content: str | None = None


@dataclass(frozen=True)
class AdapterChoice:
    """归一化后的候选。"""

    message: AdapterMessage = field(default_factory=AdapterMessage)
    index: int = 0
    finish_reason: str | None = None


@dataclass(frozen=True)
class AdapterResponse:
    """归一化后的完成响应。

    形状与 litellm ``ModelResponse`` 的读取面一致，便于既有代码零改动复用
    ``extract_usage`` / ``has_complete_usage``。

    ``usage`` 保留 provider 原始载荷（dict）：``extract_usage`` 已支持 dict
    读取，且 provider 的缓存 token 字段名各不相同，原样保留才不会丢信息。
    """

    choices: list[AdapterChoice] = field(default_factory=list)
    usage: dict[str, Any] | None = None
    model: str | None = None


@dataclass(frozen=True)
class NativeRequest:
    """自有传输层的一次请求。

    ``model`` 是**发给 provider 的裸模型名**（不含 provider 前缀），
    ``base_url`` 是**已解析的 endpoint 前缀**。两者都由 registry 依据模型
    配置解析，传输实现只负责按 OpenAI 兼容协议发出去。
    """

    model: str
    base_url: str
    api_key: str | None
    messages: list
    temperature: float | None
    max_tokens: int | None
    response_format: dict[str, Any] | None
    timeout: float
    headers: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class LlmAdapter(Protocol):
    """传输实现协议。

    失败时抛 :mod:`app.services.llm.adapters.errors` 里的自有错误类型；
    成功时返回 :class:`AdapterResponse`。
    """

    name: str

    async def complete(self, request: NativeRequest) -> AdapterResponse: ...
