"""调用前上下文窗口预检（fail-open）。

复用 ``_rate_limit.estimate_request_tokens``（chars/4 + max_tokens）做本地
估算——对中文内容会**低估** token 数，低估方向对 fail-open 预检是安全的：
只有估算严格大于窗口才判 unfit，误杀概率被低估偏置进一步压低。
真实超窗仍由 litellm 抛 ContextWindowExceededError 兜底（V1 行为不变）。
"""

from __future__ import annotations

from typing import Any

from app.services.llm._rate_limit import estimate_request_tokens


class LlmContextWindowExceededError(RuntimeError):
    """全部候选模型的上下文窗口都放不下当前请求。

    确定性请求问题（换渠道重试无解），与 litellm 的
    ContextWindowExceededError 同类：不计入候选失败冷却，也不得污染
    全局路由熔断器（见 _call_engine._is_deterministic_request_error）。
    """


def context_guard_verdict(
    model_config: Any,
    messages: list,
    max_tokens: int,
) -> tuple[bool, int, int | None]:
    """返回 (unfit, estimated_tokens, context_window)。

    unfit=False 表示放行（未配置窗口 / 估算未超）。纯函数，无 IO，
    供 provider 候选循环与单测复用。
    """
    context_window = getattr(model_config, "context_window", None)
    try:
        context_window = int(context_window) if context_window is not None else None
    except (TypeError, ValueError):
        context_window = None
    if not context_window or context_window <= 0:
        return False, 0, None

    estimated = estimate_request_tokens(messages, max_tokens)
    return estimated > context_window, estimated, context_window
