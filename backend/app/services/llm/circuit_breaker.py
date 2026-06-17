"""
LLM circuit breaker — 防止 LLM 持续故障时浪费配额 + 拖慢抓取。

状态机：
  CLOSED  → 正常调用。失败计数累加。
  OPEN    → 连续失败达阈值，熔断。所有调用直接抛 CircuitOpenError，
            不实际调 LLM。持续 cooldown_seconds 后转 HALF_OPEN。
  HALF_OPEN → 放一个请求试探。成功 → CLOSED；失败 → 重新 OPEN。

线程安全：单进程 asyncio，用 asyncio.Lock 保护状态转换。
"""

from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum, StrEnum
from typing import Optional

logger = logging.getLogger(__name__)


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(Exception):
    """熔断器开启时抛出，调用方应走 fallback 路径。"""


class CircuitBreaker:
    """简单的单进程 LLM 熔断器。"""

    def __init__(
        self,
        *,
        failure_threshold: int = 5,
        cooldown_seconds: float = 300,
        name: str = "llm",
    ):
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.name = name

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float | None = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        return self._state

    async def allow_request(self) -> bool:
        """检查是否允许发起请求。允许时返回 True；熔断时返回 False。"""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                # 检查 cooldown 是否已过
                if self._last_failure_time and (time.monotonic() - self._last_failure_time >= self.cooldown_seconds):
                    self._state = CircuitState.HALF_OPEN
                    logger.info(
                        "CircuitBreaker[%s]: OPEN → HALF_OPEN (cooldown elapsed, probing)",
                        self.name,
                    )
                    return True
                return False
            # CLOSED 或 HALF_OPEN 都允许请求
            return True

    async def record_success(self) -> None:
        async with self._lock:
            if self._state != CircuitState.CLOSED:
                logger.info(
                    "CircuitBreaker[%s]: %s → CLOSED (success)",
                    self.name,
                    self._state.value,
                )
            self._state = CircuitState.CLOSED
            self._failure_count = 0

    async def record_failure(self) -> None:
        async with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()

            if self._state == CircuitState.HALF_OPEN:
                # 试探失败，重新 OPEN
                self._state = CircuitState.OPEN
                logger.warning(
                    "CircuitBreaker[%s]: HALF_OPEN → OPEN (probe failed)",
                    self.name,
                )
                return

            if self._failure_count >= self.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "CircuitBreaker[%s]: CLOSED → OPEN (consecutive failures=%d, cooldown=%.0fs)",
                    self.name,
                    self._failure_count,
                    self.cooldown_seconds,
                )

    def status(self) -> dict:
        """当前状态快照（用于 /metrics / health 暴露）。"""
        return {
            "name": self.name,
            "state": self._state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "last_failure_ago_seconds": (
                round(time.monotonic() - self._last_failure_time, 1) if self._last_failure_time else None
            ),
        }


# 全局单例（单进程足够；多进程需换 Redis 实现）
_default_breaker: CircuitBreaker | None = None


def get_llm_circuit_breaker() -> CircuitBreaker:
    global _default_breaker
    if _default_breaker is None:
        _default_breaker = CircuitBreaker(name="llm_default")
    return _default_breaker
