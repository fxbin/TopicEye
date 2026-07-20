"""PickMark Repository.

封装用户对日报选题标记（write/watch/skip）的 ORM 操作。

业务逻辑（如周报 pick-tracking 的标题模糊匹配）仍留在 api/service 层，
本 repo 只负责纯粹的 CRUD + 按 user/date/title 范围查询。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date as date_type

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.pick_mark import PickMark
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class PickMarkRepository(BaseRepository[PickMark]):
    """PickMark repository，按 (user_id, report_date, pick_title) 三元组管理标记。"""

    model = PickMark

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def list_by_user(
        self,
        user_id: int,
        report_date: date_type | None = None,
    ) -> Sequence[PickMark]:
        """按用户查标记列表；可选按日报日期过滤。

        排序：updated_at DESC（与历史行为等价）。
        """
        stmt = select(self.model).where(self.model.user_id == user_id)
        if report_date is not None:
            stmt = stmt.where(self.model.report_date == report_date)
        stmt = stmt.order_by(self.model.updated_at.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_by_user_date_range(
        self,
        user_id: int,
        start_date: date_type,
        end_date: date_type,
    ) -> Sequence[PickMark]:
        """按用户 + 日期范围查标记，供周报 pick-tracking 统计使用。

        排序：report_date ASC（与历史行为等价，便于按日遍历）。
        """
        stmt = (
            select(self.model)
            .where(
                self.model.user_id == user_id,
                self.model.report_date >= start_date,
                self.model.report_date <= end_date,
            )
            .order_by(self.model.report_date)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def find_existing(
        self,
        user_id: int,
        report_date: date_type,
        pick_title: str,
    ) -> PickMark | None:
        """按 (user, date, title) 唯一键查现有标记，供 upsert 端点使用。"""
        stmt = select(self.model).where(
            self.model.user_id == user_id,
            self.model.report_date == report_date,
            self.model.pick_title == pick_title,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_user_date_title(
        self,
        user_id: int,
        report_date: date_type,
        pick_title: str,
    ) -> int:
        """按 (user, date, title) 删除标记，返回受影响行数。"""
        stmt = delete(self.model).where(
            self.model.user_id == user_id,
            self.model.report_date == report_date,
            self.model.pick_title == pick_title,
        )
        result = await self.db.execute(stmt)
        return result.rowcount or 0

    def add_new(
        self,
        *,
        user_id: int,
        report_date: date_type,
        pick_title: str,
        action: str,
        pick_category: str | None = None,
        pick_source_url: str | None = None,
    ) -> PickMark:
        """创建并 db.add 一个新标记，返回实例引用（不 flush/refresh）。

        供 upsert_pick_mark 端点使用——api 层不直接 import ORM 模型类，
        也不直接 db.add。事务边界（db.commit）由调用方控制，
        与历史行为完全等价（原 db.add 后由 api 层 db.commit）。
        """
        mark = self.model(
            user_id=user_id,
            report_date=report_date,
            pick_title=pick_title,
            action=action,
            pick_category=pick_category,
            pick_source_url=pick_source_url,
        )
        self.db.add(mark)
        return mark
