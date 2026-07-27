"""
Repository for User model operations.

提供用户管理相关的查询封装，包括：
- 分页列表（支持 keyword/role/plan/is_active 筛选）
- 活跃 admin 数量统计（用于"不能封禁最后一个 admin"护栏）
- 批量查询用户 OAuth provider 列表（避免 N+1）
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, or_, select

from app.models.user import User, UserOAuthAccount
from app.repositories.base import BaseRepository
from app.services.auth_service import normalize_email


class UserRepository(BaseRepository[User]):
    """用户表 CRUD + 管理后台所需的查询封装。"""

    model = User

    async def get_by_email(self, email: str) -> User | None:
        """按邮箱查找用户（normalized），用于唯一性检查。"""
        result = await self.db.execute(
            select(User).where(User.email == normalize_email(email))
        )
        return result.scalar_one_or_none()

    async def count_active_admins(self) -> int:
        """统计当前活跃 admin 数量。

        供 _assert_not_last_admin 护栏使用：封禁或降级 admin 前确保至少剩一个活跃 admin。
        """
        result = await self.db.execute(
            select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
        )
        return int(result.scalar() or 0)

    async def list_with_filters(
        self,
        *,
        keyword: str | None = None,
        role: str | None = None,
        plan: str | None = None,
        is_active: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[User], int]:
        """分页查询用户列表，支持 keyword/role/plan/is_active 筛选。

        keyword 模糊匹配 email / display_name（OR ILIKE）。
        排序：created_at DESC。与 list_users 端点历史行为等价。
        返回 (items, total)。
        """
        stmt = select(User)
        count_stmt = select(func.count()).select_from(User)
        filters = []
        cleaned = keyword.strip() if keyword else ""
        if cleaned:
            pattern = f"%{cleaned}%"
            filters.append(or_(User.email.ilike(pattern), User.display_name.ilike(pattern)))
        if role is not None:
            filters.append(User.role == role)
        if plan is not None:
            filters.append(User.plan == plan)
        if is_active is not None:
            filters.append(User.is_active.is_(is_active))
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)
        total = int(await self.db.scalar(count_stmt) or 0)
        stmt = stmt.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def list_oauth_providers_by_user_ids(self, user_ids: list[int]) -> dict[int, list[str]]:
        """批量查询多个用户的 OAuth provider 列表，返回 {user_id: [provider, ...]}。

        供 list_users 端点一次性拉取本页用户的 OAuth provider，避免 N+1。
        """
        if not user_ids:
            return {}
        result = await self.db.execute(
            select(UserOAuthAccount.user_id, UserOAuthAccount.provider).where(
                UserOAuthAccount.user_id.in_(user_ids)
            )
        )
        oauth_map: dict[int, list[str]] = {}
        for uid, provider in result.all():
            oauth_map.setdefault(uid, []).append(provider)
        return oauth_map
