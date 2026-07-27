"""
LLM 模型配置缓存。

- `ModelConfigCache` 每 60 秒从 DB 刷新启用的模型路由配置
- 全局单例 `_model_cache`

从 provider.py 拆出，无反向依赖 provider。
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class ModelConfigCache:
    """
    Caches enabled model route configs from DB.
    Refreshes every 60 seconds so changes in the UI take effect quickly.
    """

    def __init__(self):
        self._route_models: list[Any] = []
        self._last_refresh = 0.0
        self._lock = asyncio.Lock()

    async def refresh(self):
        """Reload system-level model configs from DB."""
        try:
            from sqlalchemy import select

            from app.core.database import async_session
            from app.models.llm_model import LlmModel

            async with async_session() as session:
                result = await session.execute(
                    select(LlmModel)
                    .where(LlmModel.enabled is True)
                    .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
                )
                models = result.scalars().all()

            self._route_models = list(models)
            self._last_refresh = time.monotonic()
            logger.debug("ModelConfigCache: %d system route models loaded", len(models))
        except Exception as e:
            logger.warning("ModelConfigCache refresh failed: %s", e)

    async def get_route_models(self, routing_group: str = "default"):
        now = time.monotonic()
        if now - self._last_refresh > 60:
            async with self._lock:
                if time.monotonic() - self._last_refresh > 60:
                    await self.refresh()
        group = (routing_group or "default").strip() or "default"
        models = [m for m in self._route_models if (m.routing_group or "default") == group]
        if models:
            return models
        return self._route_models


_model_cache = ModelConfigCache()
