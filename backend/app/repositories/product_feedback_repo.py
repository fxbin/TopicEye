"""
Repository for IssueFeedback + ProductUpdate — product feedback subsystem.

封装产品反馈子系统的查询：
- IssueFeedback 的 CRUD + 按状态计数 + 带 reporter 的 JOIN 查询
- ProductUpdate 的列表查询（含 shipped 优先排序）

两个 model 同属 product_feedback 模块，查询逻辑相关，放同一 repo 文件。
但分别用两个 Repository 类，保持各自 model 的 BaseRepository 泛型继承。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import case as sa_case, func, select

from app.models.product_feedback import (
    IssueFeedback,
    IssueFeedbackStatus,
    ProductUpdate,
    ProductUpdateStatus,
)
from app.models.user import User
from app.repositories.base import BaseRepository

_OPEN_STATUSES = [
    IssueFeedbackStatus.open,
    IssueFeedbackStatus.triaged,
    IssueFeedbackStatus.in_progress,
]


class IssueFeedbackRepository(BaseRepository[IssueFeedback]):
    """IssueFeedback 查询 + 带 User JOIN 的聚合查询。"""

    model = IssueFeedback

    async def count_issues_by_status(
        self,
        *,
        user_id: int | None = None,
    ) -> tuple[int, int]:
        """返回 (open_count, fixed_count)。

        open_count: status in (open, triaged, in_progress) 的条数
        fixed_count: status == fixed 的条数

        user_id 非空时只统计该用户的反馈。
        """
        filters = []
        if user_id is not None:
            filters.append(IssueFeedback.user_id == user_id)

        open_stmt = select(func.count(IssueFeedback.id)).where(
            *filters,
            IssueFeedback.status.in_(_OPEN_STATUSES),
        )
        fixed_stmt = select(func.count(IssueFeedback.id)).where(
            *filters,
            IssueFeedback.status == IssueFeedbackStatus.fixed,
        )
        open_result = await self.db.execute(open_stmt)
        fixed_result = await self.db.execute(fixed_stmt)
        return int(open_result.scalar() or 0), int(fixed_result.scalar() or 0)

    async def count_user_issues(
        self,
        *,
        user_id: int,
        status: IssueFeedbackStatus | None = None,
    ) -> int:
        """按 status 过滤统计当前用户的反馈条数。"""
        stmt = select(func.count(IssueFeedback.id)).where(IssueFeedback.user_id == user_id)
        if status is not None:
            stmt = stmt.where(IssueFeedback.status == status)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_user_issues(
        self,
        *,
        user_id: int,
        status: IssueFeedbackStatus | None = None,
        limit: int,
        offset: int,
    ) -> Sequence[IssueFeedback]:
        """按 status 过滤查询当前用户的反馈列表，按 created_at/id 倒序分页。"""
        stmt = select(IssueFeedback).where(IssueFeedback.user_id == user_id)
        if status is not None:
            stmt = stmt.where(IssueFeedback.status == status)
        stmt = stmt.order_by(IssueFeedback.created_at.desc(), IssueFeedback.id.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_all_issues(
        self,
        *,
        status: IssueFeedbackStatus | None = None,
        severity: str | None = None,
        area: str | None = None,
    ) -> int:
        """按 status/severity/area 过滤统计全量反馈条数（admin 视图）。"""
        stmt = select(func.count(IssueFeedback.id))
        if status is not None:
            stmt = stmt.where(IssueFeedback.status == status)
        if severity:
            stmt = stmt.where(IssueFeedback.severity == severity)
        if area:
            stmt = stmt.where(IssueFeedback.area == area)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_all_issues_with_reporter(
        self,
        *,
        status: IssueFeedbackStatus | None = None,
        severity: str | None = None,
        area: str | None = None,
        limit: int,
        offset: int,
    ) -> Sequence[tuple[IssueFeedback, User | None]]:
        """按 status/severity/area 过滤查询全量反馈 + reporter，按 created_at/id 倒序分页。

        返回元组 (IssueFeedback, User | None)，User 用 left join 兼容匿名反馈。
        """
        stmt = select(IssueFeedback, User).outerjoin(User, User.id == IssueFeedback.user_id)
        if status is not None:
            stmt = stmt.where(IssueFeedback.status == status)
        if severity:
            stmt = stmt.where(IssueFeedback.severity == severity)
        if area:
            stmt = stmt.where(IssueFeedback.area == area)
        stmt = stmt.order_by(IssueFeedback.created_at.desc(), IssueFeedback.id.desc()).limit(limit).offset(offset)
        result = await self.db.execute(stmt)
        return result.all()

    async def get_issue_with_reporter(
        self,
        issue_id: int,
    ) -> tuple[IssueFeedback, User | None] | None:
        """按 id 查询单条反馈 + reporter，不存在返回 None。"""
        stmt = (
            select(IssueFeedback, User)
            .outerjoin(User, User.id == IssueFeedback.user_id)
            .where(IssueFeedback.id == issue_id)
        )
        result = await self.db.execute(stmt)
        return result.first()

    def add_instance(self, issue: IssueFeedback) -> None:
        """将外部已构造的 IssueFeedback 实例加入 session。

        供 create_issue_feedback 端点使用，不 flush，调用方负责事务边界。
        """
        self.db.add(issue)


class ProductUpdateRepository(BaseRepository[ProductUpdate]):
    """ProductUpdate 查询，含 shipped 优先排序。"""

    model = ProductUpdate

    async def count_updates(
        self,
        *,
        status: ProductUpdateStatus | None = None,
    ) -> int:
        """按 status 过滤统计 ProductUpdate 条数。"""
        stmt = select(func.count(ProductUpdate.id))
        if status is not None:
            stmt = stmt.where(ProductUpdate.status == status)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def list_updates(
        self,
        *,
        status: ProductUpdateStatus | None = None,
        limit: int,
        offset: int,
    ) -> Sequence[ProductUpdate]:
        """按 status 过滤查询 ProductUpdate 列表，shipped 在前，同档按 shipped_at/updated_at 倒序。"""
        stmt = select(ProductUpdate)
        if status is not None:
            stmt = stmt.where(ProductUpdate.status == status)
        stmt = (
            stmt.order_by(
                sa_case(
                    (ProductUpdate.status == ProductUpdateStatus.shipped, 1),
                    else_=0,
                ).desc(),
                ProductUpdate.shipped_at.desc().nullslast(),
                ProductUpdate.updated_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def add_instance(self, update: ProductUpdate) -> None:
        """将外部已构造的 ProductUpdate 实例加入 session。

        供 create_product_update 端点使用，不 flush，调用方负责事务边界。
        """
        self.db.add(update)

    async def delete_instance(self, update: ProductUpdate) -> None:
        """删除已加载的 ProductUpdate 实例并 flush。"""
        await self.db.delete(update)
        await self.db.flush()
