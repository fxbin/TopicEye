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
        self._user_route_models: dict[int, list[Any]] = {}
        self._last_refresh = 0.0
        self._user_last_refresh: dict[int, float] = {}
        self._lock = asyncio.Lock()

    async def refresh(self, user_id: int | None = None):
        """Reload model configs from DB."""
        try:
            from sqlalchemy import select

            from app.core.database import async_session
            from app.models.llm_model import LlmModel
            from app.models.user import User
            from app.services.plan_catalog import plan_allows_custom_ai

            async with async_session() as session:
                filters = [LlmModel.enabled == True]
                if user_id is None:
                    filters.append(LlmModel.owner_user_id.is_(None))
                else:
                    plan = await session.scalar(select(User.plan).where(User.id == user_id))
                    if not plan_allows_custom_ai(plan):
                        self._user_route_models[user_id] = []
                        self._user_last_refresh[user_id] = time.monotonic()
                        return
                    filters.append(LlmModel.owner_user_id == user_id)
                result = await session.execute(
                    select(LlmModel)
                    .where(*filters)
                    .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
                )
                models = result.scalars().all()

                if user_id is None:
                    self._route_models = list(models)
                    self._last_refresh = time.monotonic()
                    logger.debug("ModelConfigCache: %d system route models loaded", len(models))
                else:
                    self._user_route_models[user_id] = list(models)
                    self._user_last_refresh[user_id] = time.monotonic()
                    logger.debug("ModelConfigCache: %d user route models loaded for user=%s", len(models), user_id)
        except Exception as e:
            logger.warning("ModelConfigCache refresh failed: %s", e)

    async def _get_system_route_models(self, routing_group: str = "default"):
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

    async def _get_user_route_models(self, user_id: int, routing_group: str = "default"):
        now = time.monotonic()
        if now - self._user_last_refresh.get(user_id, 0.0) > 60:
            async with self._lock:
                if time.monotonic() - self._user_last_refresh.get(user_id, 0.0) > 60:
                    await self.refresh(user_id=user_id)
        group = (routing_group or "default").strip() or "default"
        user_models = self._user_route_models.get(user_id, [])
        models = [m for m in user_models if (m.routing_group or "default") == group]
        if models:
            return models
        return user_models

    async def get_route_models(self, routing_group: str = "default", user_id: int | None = None):
        system_models = await self._get_system_route_models(routing_group)
        if user_id is None:
            return system_models
        user_models = await self._get_user_route_models(user_id, routing_group)
        return [*user_models, *system_models]


_model_cache = ModelConfigCache()
