"""
LLM 模型故障转移状态跟踪。

- `ModelFailover` 跟踪每个模型的健康状态（HEALTHY / DEGRADED）与冷却时间
- 全局单例 `_failover`
- 候选构造 `_candidate_from_db_model`

从 provider.py 拆出。依赖 model_resolver，无反向依赖 provider。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.llm.model_resolver import resolve_litellm_model
from app.services.secret_store import decrypt_secret

logger = logging.getLogger(__name__)


class ModelFailover:
    """
    Tracks per-model health and manages automatic failover chains.

    States:
    - HEALTHY: model is working normally
    - DEGRADED: model failed, skip until its reset time
    """

    HEALTHY = "healthy"
    DEGRADED = "degraded"

    def __init__(self):
        self._cooldowns: dict[str, datetime] = {}
        self._lock = threading.Lock()

    def on_failure(self, key: str, *, reset_at: datetime | None = None, cooldown_seconds: int = 300):
        """Called when a model fails. Pass reset_at if the provider supplied one."""
        cooldown = max(cooldown_seconds or 300, 1)
        effective_reset = reset_at or (datetime.now(UTC) + timedelta(seconds=cooldown))
        with self._lock:
            self._cooldowns[key] = effective_reset
        logger.warning("ModelFailover: %s degraded until %s", key, effective_reset)

    def on_success(self, key: str):
        """Called after a successful LLM call."""
        with self._lock:
            if key in self._cooldowns:
                logger.info("ModelFailover: %s recovered", key)
                self._cooldowns.pop(key, None)

    def reset(self):
        """Reset failover state after model configuration changes."""
        with self._lock:
            self._cooldowns.clear()

    def should_skip(self, key: str) -> bool:
        """Return True if this model is still cooling down."""
        with self._lock:
            reset_at = self._cooldowns.get(key)
            if not reset_at:
                return False
            if datetime.now(UTC) < reset_at:
                return True
            logger.info("ModelFailover: cooldown passed, trying %s", key)
            self._cooldowns.pop(key, None)
            return False

    def next_available_at(self, keys: Iterable[str]) -> datetime | None:
        """Return the earliest future cooldown expiry among ``keys``.

        This lets callers distinguish a temporarily exhausted route from a
        missing route configuration, without probing a known-cooling endpoint.
        """
        now = datetime.now(UTC)
        with self._lock:
            ready_times = [
                reset_at for key in keys if (reset_at := self._cooldowns.get(key)) is not None and reset_at > now
            ]
        return min(ready_times) if ready_times else None


# Global failover tracker
_failover = ModelFailover()


def _model_key(model_config: Any) -> str:
    return f"db:{model_config.id}"


def _candidate_from_db_model(model_config: Any, temperature: float, max_tokens: int) -> dict[str, Any]:
    return {
        "request_model": resolve_litellm_model(model_config),
        "api_key": decrypt_secret(model_config.api_key),
        "api_base": model_config.api_base,
        "temperature": temperature if temperature is not None else model_config.temperature,
        "max_tokens": max_tokens if max_tokens is not None else model_config.max_tokens,
        "model_config": model_config,
        "cooldown_seconds": model_config.cooldown_seconds or 300,
    }
