"""自有传输层错误分类。

设计要点（issue #181）：

传输层（不管 litellm 还是自有实现）最终都要让编排层按同一套语义做决定：
限流 → 不重试、切下一候选；确定性请求错（400 族）→ 不重试、不降级、
不污染熔断器。因此这里定义**自有**错误类型，再由
:func:`to_litellm_exception` 映射回既有的 litellm 异常类型，让
`_call_engine._is_deterministic_request_error` / `_should_retry` /
`provider.py` 的 `except UnsupportedParamsError` 回退逻辑一行都不用改。

分类口径**逐条对齐 litellm 1.103.1 的 `_map_openai_exception`**（OpenAI
兼容族）。litellm 的判定顺序是「先看错误串特征，再看状态码」，本模块照抄，
连**大小写敏感度**都照抄——特征串在 litellm 侧是大小写敏感的匹配，
自家路径若改成不敏感，同一个响应在两条路径下就会得出不同结论。

判定用的错误串与 litellm **逐字节同形**：openai SDK 抛出的异常消息是
``Error code: {status} - {body}``，其中 ``{body}`` 是**解析后的 JSON 再按
Python repr 渲染**（不是原始响应文本）。自家路径照此渲染，特征串才会落在
同一个位置。

**判定用的串与异常消息是两回事**：litellm 抛出的异常消息用的是 provider
那句可读文本（``error.message``），不是上面那个大串。自家路径照此分开处理
——仓库里有按消息字符串做的判定（``_is_bad_request_error`` 认
``"error code: 400"``），两者混用会让同一个 provider 响应在两条路径下得出
「是否重试」的不同结论。

判定顺序（与 litellm 一一对应）：

1. 限流：``\\b429\\b``（状态码也是 429 时）/ ``rate limit`` 变体 /
   ``service tier capacity exceeded``
2. 上下文超窗：已知超窗特征串（带 litellm 的两条排除规则）
3. ``invalid_request_error`` + ``model_not_found`` → 模型不存在
4. ``A timeout occurred`` → 超时
5. 内容策略：``content_policy_violation`` / ``violating our usage policy`` /
   ``rejected as a result of the safety system``
6. ``invalid_encrypted_content`` → 请求错
7. ``invalid_request_error``（且不是 api key 报错）→ 请求错
8. 服务端未知错误 → 服务端错
9. ``Request too large`` → 限流
10. 缺 api key → 鉴权错
11. 状态码兜底：400/422 请求错、401 鉴权、404 不存在、408/504 超时、
    429 限流、5xx 服务端、其余 APIError

**与 litellm 的一处刻意差异**：provider 在服务端拒绝 ``response_format`` 时，
litellm 侧靠客户端参数表预检抛 ``UnsupportedParamsError``，自家路径改为识别
服务端 400 里的参数名。二者最终都让 ``provider.py`` 的「去掉该参数重试」
分支生效，编排决策一致。
"""

from __future__ import annotations

import json
import re
from typing import Any


class LlmAdapterError(Exception):
    """自有传输层错误基类。

    携带 HTTP 状态码与 provider 原始响应体，便于日志排查与错误摘要。
    """

    def __init__(self, message: str, *, status_code: int | None = None, body: str | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


class LlmRateLimitError(LlmAdapterError):
    """限流 / 配额耗尽。不重试，failover 切下一候选。"""


class LlmBadRequestError(LlmAdapterError):
    """确定性请求错（400 族）。不重试、不降级、不污染熔断器。"""


class LlmContentPolicyError(LlmBadRequestError):
    """内容策略 / 安全过滤拒绝。"""


class LlmContextWindowError(LlmBadRequestError):
    """上下文窗口超限。"""


class LlmUnsupportedParamsError(LlmBadRequestError):
    """provider 不支持所传参数（如 response_format）。可去掉参数重试。"""


class LlmNotFoundError(LlmAdapterError):
    """模型 / 端点不存在（404）。"""


class LlmAuthenticationError(LlmAdapterError):
    """鉴权失败（401/403）。"""


class LlmTimeoutError(LlmAdapterError):
    """请求超时（408/504）。"""


class LlmServerError(LlmAdapterError):
    """provider 侧 5xx。"""


class LlmApiError(LlmAdapterError):
    """其它无法归类的 provider 错误。"""


class LlmTransportError(LlmAdapterError):
    """连接失败 / 响应不可解析。"""


# ── litellm 的错误串特征（逐条抄自 _map_openai_exception）──────────────────

# ExceptionCheckers.is_error_str_rate_limit
_RATE_LIMIT_PATTERN = re.compile(r"rate[\s_\-]*limit")
_RATE_LIMIT_STATUS_MARKER = re.compile(r"\b429\b")

# ExceptionCheckers.is_error_str_context_window_exceeded
_CONTEXT_WINDOW_PATTERNS = (
    "exceed context limit",
    "this model's maximum context length is",
    "string too long. expected a string with maximum length",
    "model's maximum context limit",
    "is longer than the model's context length",
    "input tokens exceed the configured limit",
    "`inputs` tokens + `max_new_tokens` must be",
    "exceeds the available context size",
    "exceeds the maximum number of tokens allowed",
)

# litellm 的内容策略分支
_CONTENT_POLICY_MARKERS = (
    "invalid_request_error",
    "content_policy_violation",
)
_CONTENT_POLICY_PROMPT_MARKERS = (
    "Invalid prompt",
    "violating our usage policy",
)
_CONTENT_POLICY_LOWER = "request was rejected as a result of the safety system"

# litellm 的「模型不存在」分支
_MODEL_NOT_FOUND_MARKERS = (
    "invalid_request_error",
    "model_not_found",
)

# litellm 的「连接被拒」分支（形如 Response errored with 400 while streaming）
_TIMEOUT_MARKER = "A timeout occurred"

# litellm 的「encrypted content 校验失败」分支
_ENCRYPTED_CONTENT_MARKERS = (
    "invalid_encrypted_content",
    "could not be verified",
)

# litellm 的「未知服务端错误」分支
_SERVER_ERROR_MARKERS = (
    "Web server is returning an unknown error",
    "The server had an error processing your request.",
)

# litellm 的「请求体过大」分支
_REQUEST_TOO_LARGE_MARKER = "Request too large"

# litellm 的「缺 api key」分支（大小写敏感，原文照抄）
_MISSING_API_KEY_MARKER = (
    "The api_key client option must be set either by passing api_key to the client "
    "or by setting the OPENAI_API_KEY environment variable"
)

# 服务端拒绝参数的特征。**不用于改判 400**：litellm 对服务端 400 一律归
# ``BadRequestError``（确定性请求错）。自家路径必须跟这条一致，否则同一个
# provider 响应在两条路径下会得到不同的编排结论（一个切下一候选、一个直接
# 抛错）。「参数不被支持」由**客户端预检**识别，见 ``openai_compat``。
_UNSUPPORTED_PARAM_MARKERS = (
    "unsupported parameter",
    "unsupported_parameter",
    "not supported",
    "does not support",
    "is not supported by",
    "unrecognized request argument",
    "unknown parameter",
    "invalid parameter",
)
_UNSUPPORTED_PARAM_NAMES = ("response_format",)


def _contains_all(text: str, needles: tuple[str, ...]) -> bool:
    return all(needle in text for needle in needles)


def format_provider_message(status_code: int, body: str) -> str:
    """按 openai SDK 的形状拼 provider 错误消息。

    openai SDK（``_base_client._make_status_error_from_response``）的行为是：

    - 响应体是 JSON → 先 ``json.loads``，再把**解析后的对象**按 Python repr
      渲染，拼成 ``Error code: {status} - {body}``；
    - 不是 JSON → 直接用原始文本。

    自家路径照此渲染，判定用的错误串才与 litellm 参与判定的那个**逐字节
    同形**。差异不只是好看：JSON 里被转义成 ``\\uXXXX`` 的中文，在 repr 后
    是可读原文，按原始文本匹配就会漏判。
    """
    text = (body or "").strip()
    if not text:
        return f"Error code: {status_code}"
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    return f"Error code: {status_code} - {parsed}"


def extract_provider_message(status_code: int, body: str) -> str:
    """取 provider 的可读消息，取法与 litellm 的 ``get_error_message`` 一致。

    litellm 侧参与异常消息的是 provider 自己那句可读文本（``error.message``），
    **不是** ``Error code: {status} - {body}`` 那个大串。自家路径若把大串直接
    当消息，仓库里按字符串做的判定就会漂移：``_is_bad_request_error`` 认
    ``"error code: 400"``，而 litellm 的 NotFoundError（400 + model_not_found）
    消息里没有这句——同一个响应在两条路径下会得出「是否重试」的不同结论。

    取不到可读消息时退回 openai SDK 的原始异常消息，与 litellm 一致。
    """
    text = (body or "").strip()
    if not text:
        return f"Error code: {status_code}"
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text
    if isinstance(parsed, dict):
        if parsed.get("message"):
            return str(parsed["message"])
        nested = parsed.get("error")
        if isinstance(nested, dict) and nested.get("message"):
            return str(nested["message"])
    return format_provider_message(status_code, text)


def _is_context_window_exceeded(error_str: str) -> bool:
    """上下文超窗判定，口径与 litellm 的同名检查逐条一致（含两条排除规则）。"""
    lowered = error_str.lower()
    # 排除规则 1：参数校验错误（OpenAI 的 user 参数最长 64 字符）。
    if "string_above_max_length" in lowered:
        return False
    # 排除规则 2：同上。
    if "invalid 'user'" in lowered and "string too long" in lowered:
        return False
    if any(pattern in lowered for pattern in _CONTEXT_WINDOW_PATTERNS):
        return True
    # Cerebras 句式。
    if "current length is" in lowered and "while limit is" in lowered:
        return True
    return "maximum input length is" in lowered and "tokens" in lowered


def classify_status_error(status_code: int, body: str) -> LlmAdapterError:
    """按 litellm 的判定顺序给出自有错误类型。

    ``body`` 是 provider 的**原始响应体**（特征串常出现在 ``type``/``code``
    等字段，只取 ``error.message`` 会漏判）。
    """
    text = body or ""
    # 与 litellm 侧参与判定的错误串同形（openai SDK: "Error code: {s} - {body}"）。
    error_str = format_provider_message(status_code, text)
    # 异常**消息**用 provider 的可读文本（litellm 侧同源），与判定用的错误串
    # 不是一回事——两者混用会让仓库按字符串做的判定在两条路径下漂移。
    provider_message = extract_provider_message(status_code, text)

    def build(exc_cls, message: str | None = None) -> LlmAdapterError:
        return exc_cls(  # type: ignore[return-value]
            message if message is not None else provider_message,
            status_code=status_code,
            body=text[:2000],
        )

    # 1) 限流。litellm 的裸 429 判定带状态码闸门——provider 回显的请求体里
    #    可能出现 token id "429"，只有状态码本身是 429 时才算数。
    if (_RATE_LIMIT_STATUS_MARKER.search(error_str) and status_code == 429) or _RATE_LIMIT_PATTERN.search(
        error_str.lower()
    ):
        return build(LlmRateLimitError)
    if "service tier capacity exceeded" in error_str.lower():
        return build(LlmRateLimitError)

    # 2) 上下文超窗
    if _is_context_window_exceeded(error_str):
        return build(LlmContextWindowError)

    # 3) 模型不存在
    if _contains_all(error_str, _MODEL_NOT_FOUND_MARKERS):
        return build(LlmNotFoundError)

    # 4) 超时
    if _TIMEOUT_MARKER in error_str:
        return build(LlmTimeoutError)

    # 5) 内容策略
    if (
        _contains_all(error_str, _CONTENT_POLICY_MARKERS)
        or _contains_all(error_str, _CONTENT_POLICY_PROMPT_MARKERS)
        or _CONTENT_POLICY_LOWER in error_str.lower()
    ):
        return build(LlmContentPolicyError)

    # 6) encrypted content 校验失败
    if any(marker in error_str for marker in _ENCRYPTED_CONTENT_MARKERS):
        return build(LlmBadRequestError)

    # 7) 明确的请求错
    if "invalid_request_error" in error_str and "Incorrect API key provided" not in error_str:
        return build(LlmBadRequestError)

    # 8) 服务端未知错误
    if any(marker in error_str for marker in _SERVER_ERROR_MARKERS):
        return build(LlmServerError)

    # 9) 请求体过大 → 限流
    if _REQUEST_TOO_LARGE_MARKER in error_str:
        return build(LlmRateLimitError)

    # 10) 缺 api key
    if _MISSING_API_KEY_MARKER in error_str:
        return build(LlmAuthenticationError)

    # 11) 状态码兜底
    if status_code in (400, 422):
        return build(LlmBadRequestError)
    if status_code == 401:
        return build(LlmAuthenticationError)
    if status_code == 404:
        return build(LlmNotFoundError)
    if status_code in (408, 504):
        return build(LlmTimeoutError)
    if status_code == 429:
        return build(LlmRateLimitError)
    if status_code in (500, 502, 503):
        return build(LlmServerError)
    return build(LlmApiError)


def to_litellm_exception(exc: LlmAdapterError, *, model: str | None = None, provider: str | None = None):
    """把自有错误映射成既有的 litellm 异常类型。

    编排层（`_call_engine` / `provider.py` / `analysis.py`）只认 litellm 的
    异常类型，映射后**既有判定语义一行都不用改**：

    - ``RateLimitError`` → `_should_retry` 返回 False（不重试），failover 切下一候选
    - ``BadRequestError`` 族 → `_is_deterministic_request_error` 为真
      （不重试、不降级、不污染熔断器）
    - ``UnsupportedParamsError`` → `provider.py` 捕获后去掉 response_format 重试

    litellm 的异常构造签名要求 ``message`` / ``model`` / ``llm_provider``。
    """
    from litellm.exceptions import (
        APIConnectionError,
        APIError,
        AuthenticationError,
        BadGatewayError,
        BadRequestError,
        ContentPolicyViolationError,
        ContextWindowExceededError,
        InternalServerError,
        NotFoundError,
        RateLimitError,
        ServiceUnavailableError,
        Timeout,
        UnsupportedParamsError,
    )

    message = str(exc)
    kwargs: dict[str, Any] = {"message": message, "model": model, "llm_provider": provider or "openai"}

    if isinstance(exc, LlmRateLimitError):
        return RateLimitError(**kwargs)
    if isinstance(exc, LlmUnsupportedParamsError):
        return UnsupportedParamsError(**kwargs)
    if isinstance(exc, LlmContentPolicyError):
        return ContentPolicyViolationError(**kwargs)
    if isinstance(exc, LlmContextWindowError):
        return ContextWindowExceededError(**kwargs)
    if isinstance(exc, LlmBadRequestError):
        return BadRequestError(**kwargs)
    if isinstance(exc, LlmAuthenticationError):
        return AuthenticationError(**kwargs)
    if isinstance(exc, LlmNotFoundError):
        return NotFoundError(**kwargs)
    if isinstance(exc, LlmTimeoutError):
        return Timeout(**kwargs)
    if isinstance(exc, LlmServerError):
        if exc.status_code == 502:
            return BadGatewayError(**kwargs)
        if exc.status_code == 503:
            return ServiceUnavailableError(**kwargs)
        return InternalServerError(**kwargs)
    if isinstance(exc, LlmTransportError):
        return APIConnectionError(**kwargs)

    return APIError(status_code=exc.status_code or 500, **kwargs)
