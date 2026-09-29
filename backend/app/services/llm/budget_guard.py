"""LLM 预算熔断闸。

三窗（分钟/小时/日）预算保险丝：按 ``llm_call_logs`` 里实际 DONE 的调用
计数，超限直接拒绝新调用（``LlmBudgetExceededError``），调用方走既有的
失败退避/降级路径。与 ``_rate_limit`` 的语义区别：限流是「等一等再发」
（保护对端配额），预算是「不再花下去」（保护自己的钱包）——拒绝而非等待。

- 各窗口上限为 0 表示关闭该窗口；三窗全 0 时零开销直通。
- 计数查询失败时 fail-open（保险丝自身故障不阻断主链路），记 warning。
- 预算拒绝写一行 ``llm_call_logs`` 审计记录（status="BUDGET_REJECTED"，
  不参与 DONE 计数），使拒绝在用量看板 ALL 视图可见。
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.llm._rate_limit import record_llm_pool_circuit_event

logger = logging.getLogger(__name__)


class LlmBudgetExceededError(Exception):
    """Rolling budget window exhausted; deterministic, must not be retried."""


def _budget_limits() -> tuple[int, int, int] | None:
    limits = (
        settings.LLM_BUDGET_CALLS_PER_MINUTE,
        settings.LLM_BUDGET_CALLS_PER_HOUR,
        settings.LLM_BUDGET_CALLS_PER_DAY,
    )
    if not any(limits):
        return None
    return limits


async def ensure_llm_budget(scene: str) -> None:
    """Raise :class:`LlmBudgetExceededError` when a budget window is exhausted."""
    limits = _budget_limits()
    if limits is None:
        return

    from app.services.llm_usage import count_recent_llm_calls

    try:
        minute_calls, hour_calls, day_calls = await count_recent_llm_calls()
    except Exception as exc:  # noqa: BLE001 — fuse failure must not block the main path
        logger.warning("LLM budget check skipped (count query failed): %s", exc)
        return

    for label, calls, limit in (
        ("minute", minute_calls, limits[0]),
        ("hour", hour_calls, limits[1]),
        ("day", day_calls, limits[2]),
    ):
        if limit > 0 and calls >= limit:
            logger.warning("LLM budget exceeded in %s window: %d/%d calls, scene=%s", label, calls, limit, scene)
            record_llm_pool_circuit_event(None, scene, "budget_rejected")
            await _record_budget_rejection(scene=scene, detail=f"{label} window: {calls}/{limit}")
            raise LlmBudgetExceededError(
                f"LLM budget exceeded in {label} window: {calls}/{limit} calls (scene={scene})"
            )


async def _record_budget_rejection(*, scene: str, detail: str) -> None:
    """审计行：BUDGET_REJECTED 不进 DONE 计数，只在用量看板可见。"""
    from app.services.llm_usage import record_llm_call_in_new_session

    try:
        await record_llm_call_in_new_session(
            model=None,
            request_model=None,
            scene=scene,
            status="BUDGET_REJECTED",
            duration_ms=0,
            error_message=detail,
        )
    except Exception as exc:  # noqa: BLE001 — 审计写失败不能影响拒绝路径本身
        logger.warning("LLM budget rejection audit log skipped: %s", exc)
