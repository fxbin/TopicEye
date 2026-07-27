"""
Repository for CreationPlan model operations.

封装用户创作方案的查询：
- 用户历史方案分页列表（per-user 隔离）
- 单条方案查询（per-user 隔离）
- 删除方案（per-user 隔离）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select

from app.models.creation import CreationPlan
from app.repositories.base import BaseRepository


class CreationPlanRepository(BaseRepository[CreationPlan]):
    """用户创作方案 CRUD（per-user 隔离）。"""

    model = CreationPlan

    async def list_user_plans(
        self,
        *,
        user_id: int,
        platform: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> Sequence[CreationPlan]:
        """按 user_id 分页查询用户历史方案，按 created_at DESC 排序。

        platform 可选，用于按平台过滤。与 list_my_plans 端点历史行为等价。
        """
        stmt = (
            select(CreationPlan)
            .where(CreationPlan.user_id == user_id)
            .order_by(CreationPlan.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        if platform:
            stmt = stmt.where(CreationPlan.platform == platform)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_user_plan(self, plan_id: int, user_id: int) -> CreationPlan | None:
        """按 plan_id + user_id 查询单条方案，不存在返回 None。

        per-user 隔离：只返回属于该用户的方案。
        """
        result = await self.db.execute(
            select(CreationPlan).where(
                CreationPlan.id == plan_id,
                CreationPlan.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def delete_user_plan(self, plan_id: int, user_id: int) -> int:
        """按 plan_id + user_id 删除方案，返回受影响行数。

        per-user 隔离：只删除属于该用户的方案。
        rowcount=0 表示方案不存在或不属于该用户。
        """
        result = await self.db.execute(
            delete(CreationPlan).where(
                CreationPlan.id == plan_id,
                CreationPlan.user_id == user_id,
            )
        )
        return result.rowcount
