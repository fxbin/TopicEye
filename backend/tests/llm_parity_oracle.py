"""litellm 时代的编排判定——parity 测试的对照组（逐字副本）。

litellm 退役（issue #204）后，编排层（``_call_engine``）的判定从 litellm
异常类型翻到了自有异常族（``adapters.errors``）。翻转是否零漂移，需要一个
「litellm 时代对同一响应会给出什么结论」的对照组。

对照组的两个成分，都不是手写的理解：

1. **真实 litellm 的异常**——测试里用 MockTransport 让 litellm 走完整的
   「发请求 → 解析错误 → 映射异常类型」链路（见
   ``test_llm_native_transport._litellm_exception_for``）。
2. **litellm 时代的判定函数**——下面三个函数逐字取自翻转前的
   ``_call_engine``（生产代码当时经 810 次真实 litellm 对照验证，见
   ``.agents/notes/implemented/architecture/2026-11-01-self-owned-llm-transport.md``）。

parity 断言因此是：``新谓词(自有异常) is legacy_谓词(真实 litellm 异常)``。
litellm 只在测试环境出现（dependency-groups 的 parity 组），运行时代码
不再 import 它。
"""

from __future__ import annotations

from litellm import RateLimitError as _LegacyRateLimitError
from litellm.exceptions import (
    BadRequestError as _LegacyBadRequestError,
    ContentPolicyViolationError as _LegacyContentPolicyViolationError,
    ContextWindowExceededError as _LegacyContextWindowExceededError,
    JSONSchemaValidationError as _LegacyJSONSchemaValidationError,
    UnprocessableEntityError as _LegacyUnprocessableEntityError,
    UnsupportedParamsError as _LegacyUnsupportedParamsError,
)

from app.services.llm._context_guard import LlmContextWindowExceededError as _OwnContextWindowExceeded
from app.services.llm.budget_guard import LlmBudgetExceededError as _OwnBudgetExceededError
from app.services.llm.call_trace import LlmTraceBudgetExceeded as _OwnTraceBudgetExceeded


def _legacy_is_rate_limit_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(
        k in msg
        for k in ["429", "rate limit", "rate_limit", "quota exceeded", "请求过于频繁", "调用额度", "额度用完", "已达"]
    )


def _legacy_is_bad_request_error(exc: Exception) -> bool:
    if isinstance(exc, _LegacyBadRequestError):
        return True
    msg = str(exc).lower()
    return "error code: 400" in msg or ("contentfilter" in msg and "400" in msg)


def legacy_is_deterministic_request_error(exc: Exception) -> bool:
    if isinstance(
        exc,
        _LegacyBadRequestError
        | _LegacyContentPolicyViolationError
        | _LegacyContextWindowExceededError
        | _LegacyJSONSchemaValidationError
        | _LegacyUnprocessableEntityError
        | _LegacyUnsupportedParamsError
        | _OwnContextWindowExceeded
        | _OwnTraceBudgetExceeded,
    ):
        return True
    return _legacy_is_bad_request_error(exc)


def legacy_should_retry(exc: BaseException) -> bool:
    if isinstance(exc, _LegacyRateLimitError | _OwnBudgetExceededError) or legacy_is_deterministic_request_error(exc):
        return False
    return not _legacy_is_rate_limit_error(exc)
