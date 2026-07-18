"""
Admin 用户管理 API。

- GET    /admin/users               分页列出用户（支持 keyword/role/plan/is_active 筛选）
- PATCH  /admin/users/{id}          改 role / is_active / plan（仅 free↔pro）
- POST   /admin/users/{id}/reset-password   管理员重置密码（撤销该用户所有 session）

整组接口 admin-only（router 级 get_current_admin_user 守卫）。
"""

from __future__ import annotations

from datetime import datetime, UTC

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import database_profile
from app.core.dependencies import get_db
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.core.validators import validate_password_strength
from app.models.user import User, UserOAuthAccount
from app.services.auth_service import hash_password, revoke_all_user_sessions

router = APIRouter(
    prefix="/admin/users",
    tags=["admin-users"],
    dependencies=[Depends(get_current_admin_user)],
)

# 改套餐仅允许 free↔pro 互转；studio/enterprise 为"规划中"，不开放手动修改
_ALLOWED_PLAN_VALUES = {"free", "pro"}


# ── 事务模板（与 llm_models.py 的 _retry_write 保持一致）─────────────


async def _retry_write(db: AsyncSession, operation):
    async def _wrapped():
        if database_profile.is_sqlite and not db.in_transaction():
            await begin_immediate_for_sqlite(db)
        return await operation()

    return await retry_sqlite_locked(_wrapped, on_retry=db.rollback)


# ── 响应 / 请求模型 ──────────────────────────────────────────────────


class UserListItem(BaseModel):
    id: int
    email: str
    display_name: str | None
    plan: str
    role: str
    is_active: bool
    has_password: bool
    oauth_providers: list[str]
    created_at: datetime | None


class UserListResponse(BaseModel):
    items: list[UserListItem]
    total: int
    page: int
    page_size: int


class UserUpdateRequest(BaseModel):
    role: str | None = Field(None, description="user / admin")
    is_active: bool | None = Field(None, description="封禁=False / 解禁=True")
    plan: str | None = Field(None, description="仅允许 free / pro 互转")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=8, max_length=128)


def _user_to_item(user: User, oauth_providers: list[str]) -> UserListItem:
    return UserListItem(
        id=user.id,
        email=user.email,
        display_name=user.display_name,
        plan=user.plan,
        role=user.role,
        is_active=user.is_active,
        has_password=bool(user.password_hash),
        oauth_providers=sorted(oauth_providers),
        created_at=user.created_at.isoformat() if user.created_at else None,
    )


# ── 安全护栏 ─────────────────────────────────────────────────────────


async def _load_user_or_404(db: AsyncSession, user_id: int) -> User:
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    return user


async def _assert_not_last_admin(db: AsyncSession, target: User) -> None:
    """封禁或降级 admin 时，确保系统中至少还剩一个活跃 admin。"""
    if target.role != "admin" and target.is_active:
        return
    count = int(
        await db.scalar(
            select(func.count(User.id)).where(User.role == "admin", User.is_active.is_(True))
        )
        or 0
    )
    if count <= 1:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="系统至少需保留一个活跃管理员，无法封禁或降级最后一个 admin",
        )


# ── Endpoints ────────────────────────────────────────────────────────


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: str | None = None,
    role: str | None = None,
    plan: str | None = None,
    is_active: bool | None = None,
    db: AsyncSession = Depends(get_db),
):
    """分页列出用户，支持按邮箱/昵称模糊搜索与角色/套餐/状态筛选。"""
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

    base = select(User)
    count_stmt = select(func.count()).select_from(User)
    for f in filters:
        base = base.where(f)
        count_stmt = count_stmt.where(f)

    total = int(await db.scalar(count_stmt) or 0)
    result = await db.execute(
        base.order_by(User.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    )
    users = list(result.scalars().all())
    if not users:
        return UserListResponse(items=[], total=total, page=page, page_size=page_size)

    # 一次性拉取本页用户的 OAuth provider 列表，避免 N+1
    user_ids = [u.id for u in users]
    oauth_rows = await db.execute(
        select(UserOAuthAccount.user_id, UserOAuthAccount.provider).where(
            UserOAuthAccount.user_id.in_(user_ids)
        )
    )
    oauth_map: dict[int, list[str]] = {}
    for uid, provider in oauth_rows.all():
        oauth_map.setdefault(uid, []).append(provider)

    items = [_user_to_item(u, oauth_map.get(u.id, [])) for u in users]
    return UserListResponse(items=items, total=total, page=page, page_size=page_size)


@router.patch("/{user_id}")
async def update_user(
    user_id: int,
    req: UserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """改 role / is_active（封禁解禁）/ plan（仅 free↔pro）。

    安全护栏：
    - 禁止封禁或降级自己（防误锁）
    - 禁止把系统最后一个活跃 admin 封禁或降级
    """
    if req.role is None and req.is_active is None and req.plan is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未提供任何更新字段")

    if req.role is not None and req.role not in {"user", "admin"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="角色仅支持 user / admin")
    if req.plan is not None and req.plan not in _ALLOWED_PLAN_VALUES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="套餐仅支持 free / pro 互转",
        )

    async def _apply():
        target = await _load_user_or_404(db, user_id)

        if target.id == current_user.id:
            # 禁止对自己执行封禁 / 降级（改自己的 plan 不受限）
            if req.is_active is False or (req.role is not None and req.role != "admin"):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="不能封禁或降级当前登录的管理员账号",
                )

        # 封禁或降级 admin 前，确保还剩至少一个活跃 admin
        will_lose_admin = (
            (req.is_active is False and target.role == "admin")
            or (req.role == "user" and target.role == "admin")
        )
        if will_lose_admin:
            await _assert_not_last_admin(db, target)

        if req.role is not None:
            target.role = req.role
        if req.is_active is not None:
            target.is_active = req.is_active
        if req.plan is not None:
            target.plan = req.plan
        await db.flush()
        return target

    target = await _retry_write(db, _apply)
    await db.commit()
    return {
        "id": target.id,
        "email": target.email,
        "role": target.role,
        "is_active": target.is_active,
        "plan": target.plan,
        "message": "用户信息已更新",
    }


@router.post("/{user_id}/reset-password")
async def reset_password(
    user_id: int,
    req: ResetPasswordRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """管理员重置某用户密码。

    - 管理员设定临时密码（明文由管理员输入并自行转交用户）
    - 重置后撤销该用户所有 session，强制用新密码重新登录
    """
    validate_password_strength(req.new_password)

    async def _apply():
        target = await _load_user_or_404(db, user_id)
        if not target.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该用户已被停用，无法重置密码",
            )
        target.password_hash = hash_password(req.new_password)
        await db.flush()
        revoked = await revoke_all_user_sessions(db, target.id)
        return target, revoked

    target, revoked = await _retry_write(db, _apply)
    await db.commit()
    return {
        "id": target.id,
        "email": target.email,
        "revoked_sessions": revoked,
        "message": "密码已重置，该用户的所有登录会话已失效",
    }
