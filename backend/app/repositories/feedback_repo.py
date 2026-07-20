"""UserFeedback Repository.

封装用户对内容项反馈（like/dislike/skip/...）的 ORM 操作。

业务逻辑（如 upsert 时判断 stale、retry on IntegrityError）仍留在 api/service 层，
本 repo 只负责纯粹的 CRUD + 按 user/content 查询 + 聚合统计。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.feedback import UserFeedback
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class FeedbackRepository(BaseRepository[UserFeedback]):
    """UserFeedback repository，按 (user_id, content_id) 维度管理反馈。"""

    model = UserFeedback

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_user_feedbacks_by_content(
        self,
        content_id: int,
        user_id: int,
    ) -> Sequence[UserFeedback]:
        """按 (content_id, user_id) 查反馈历史，按 created_at DESC, id DESC 排序。

        用于 upsert：第 0 条是当前 active 反馈，其余是 stale 待清理。
        """
        stmt = (
            select(self.model)
            .where(self.model.content_id == content_id)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc(), self.model.id.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_by_content_and_user(
        self,
        content_id: int,
        user_id: int,
    ) -> Sequence[UserFeedback]:
        """查用户在指定内容上的反馈（按 created_at DESC 排序）。

        供 GET /feedback/content/{content_id} 端点使用。
        """
        stmt = (
            select(self.model)
            .where(self.model.content_id == content_id)
            .where(self.model.user_id == user_id)
            .order_by(self.model.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def delete_by_ids(self, ids: list[int]) -> int:
        """按主键批量删除反馈，返回受影响行数。供 upsert 清理 stale 记录使用。"""
        if not ids:
            return 0
        stmt = delete(self.model).where(self.model.id.in_(ids))
        result = await self.db.execute(stmt)
        return result.rowcount or 0

    async def count_all(self) -> int:
        """统计反馈总记录数。"""
        result = await self.db.execute(select(func.count(self.model.id)))
        return result.scalar() or 0

    async def count_group_by_type(self) -> dict[str, int]:
        """按 feedback_type 分组计数，返回 {type_value: count}。"""
        stmt = (
            select(self.model.feedback_type, func.count(self.model.id))
            .group_by(self.model.feedback_type)
        )
        result = await self.db.execute(stmt)
        return {str(row[0]): row[1] for row in result.all()}

    async def avg_score_delta(self) -> float:
        """返回全部反馈的平均 score_delta。无数据返回 0.0。"""
        result = await self.db.execute(select(func.avg(self.model.score_delta)))
        return result.scalar() or 0.0
