from __future__ import annotations

from datetime import datetime, timezone, UTC
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case as sa_case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user, get_optional_current_user
from app.core.dependencies import get_db
from app.models.product_feedback import (
    IssueFeedback,
    IssueFeedbackStatus,
    ProductUpdate,
    ProductUpdateKind,
    ProductUpdateStatus,
)
from app.models.user import User
from app.schemas.product_feedback import (
    IssueFeedbackCreate,
    IssueFeedbackListResponse,
    IssueFeedbackResponse,
    IssueFeedbackUpdate,
    ProductUpdateCreate,
    ProductUpdateListResponse,
    ProductUpdatePatch,
    ProductUpdateResponse,
)

router = APIRouter(prefix="/product-feedback", tags=["product-feedback"])


def _issue_response(issue: IssueFeedback, reporter: User | None = None) -> IssueFeedbackResponse:
    return IssueFeedbackResponse(
        id=issue.id,
        user_id=issue.user_id,
        title=issue.title,
        description=issue.description,
        area=issue.area,
        severity=issue.severity,
        status=issue.status,
        resolution_note=issue.resolution_note,
        fixed_at=issue.fixed_at,
        created_at=issue.created_at,
        updated_at=issue.updated_at,
        reporter_email=reporter.email if reporter else None,
        reporter_name=reporter.display_name if reporter else None,
    )


async def _issue_counts(db: AsyncSession, user_id: int | None = None) -> tuple[int, int]:
    filters = []
    if user_id is not None:
        filters.append(IssueFeedback.user_id == user_id)

    open_result = await db.execute(
        select(func.count(IssueFeedback.id)).where(
            *filters,
            IssueFeedback.status.in_(
                [
                    IssueFeedbackStatus.open,
                    IssueFeedbackStatus.triaged,
                    IssueFeedbackStatus.in_progress,
                ]
            ),
        )
    )
    fixed_result = await db.execute(
        select(func.count(IssueFeedback.id)).where(
            *filters,
            IssueFeedback.status == IssueFeedbackStatus.fixed,
        )
    )
    return int(open_result.scalar() or 0), int(fixed_result.scalar() or 0)


@router.post("/issues", response_model=IssueFeedbackResponse, status_code=201)
async def create_issue_feedback(
    data: IssueFeedbackCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    issue = IssueFeedback(
        user_id=current_user.id if current_user else None,
        title=data.title,
        description=data.description,
        area=data.area,
        severity=data.severity,
        status=IssueFeedbackStatus.open,
    )
    db.add(issue)
    await db.flush()
    await db.refresh(issue)
    return _issue_response(issue, current_user)


@router.get("/issues/mine", response_model=IssueFeedbackListResponse)
async def list_my_issue_feedback(
    status: IssueFeedbackStatus | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    filters = [IssueFeedback.user_id == current_user.id]
    if status is not None:
        filters.append(IssueFeedback.status == status)

    total = await db.scalar(select(func.count(IssueFeedback.id)).where(*filters))
    result = await db.execute(
        select(IssueFeedback)
        .where(*filters)
        .order_by(IssueFeedback.created_at.desc(), IssueFeedback.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_issue_response(issue, current_user) for issue in result.scalars().all()]
    open_count, fixed_count = await _issue_counts(db, current_user.id)
    return IssueFeedbackListResponse(
        items=items,
        total=int(total or 0),
        open_count=open_count,
        fixed_count=fixed_count,
    )


@router.get("/issues", response_model=IssueFeedbackListResponse)
async def list_all_issue_feedback(
    status: IssueFeedbackStatus | None = Query(None),
    severity: str | None = Query(None),
    area: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    filters = []
    if status is not None:
        filters.append(IssueFeedback.status == status)
    if severity:
        filters.append(IssueFeedback.severity == severity)
    if area:
        filters.append(IssueFeedback.area == area)

    total = await db.scalar(select(func.count(IssueFeedback.id)).where(*filters))
    result = await db.execute(
        select(IssueFeedback, User)
        .outerjoin(User, User.id == IssueFeedback.user_id)
        .where(*filters)
        .order_by(IssueFeedback.created_at.desc(), IssueFeedback.id.desc())
        .limit(limit)
        .offset(offset)
    )
    items = [_issue_response(issue, reporter) for issue, reporter in result.all()]
    open_count, fixed_count = await _issue_counts(db)
    return IssueFeedbackListResponse(
        items=items,
        total=int(total or 0),
        open_count=open_count,
        fixed_count=fixed_count,
    )


@router.patch("/issues/{issue_id}", response_model=IssueFeedbackResponse)
async def update_issue_feedback(
    issue_id: int,
    data: IssueFeedbackUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    result = await db.execute(
        select(IssueFeedback, User)
        .outerjoin(User, User.id == IssueFeedback.user_id)
        .where(IssueFeedback.id == issue_id)
    )
    row = result.first()
    if row is None:
        raise HTTPException(status_code=404, detail="Issue feedback not found")

    issue, reporter = row
    if data.severity is not None:
        issue.severity = data.severity
    if data.area is not None:
        issue.area = data.area
    if data.resolution_note is not None:
        issue.resolution_note = data.resolution_note
    if data.status is not None:
        issue.status = data.status
        if data.status == IssueFeedbackStatus.fixed:
            issue.fixed_at = issue.fixed_at or datetime.now(UTC)
        else:
            issue.fixed_at = None
    issue.updated_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(issue)
    return _issue_response(issue, reporter)


# ── Product updates: 1 version = 1 record, items[] 装该版本的多条更新 ────────
# 数据全部在 DB (product_updates 表), 通过 alembic migration seed.
# 历史 BUILTIN_PRODUCT_UPDATES 已废弃, 避免数据/代码双源.


@router.get("/updates", response_model=ProductUpdateListResponse)
async def list_product_updates(
    kind: ProductUpdateKind | None = Query(None),
    status: ProductUpdateStatus | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """从 DB 查 product_updates. items 是 JSON 数组, 无法在 SQL 里筛内部字段,
    kind 过滤走 Python."""
    filters = []
    if status is not None:
        filters.append(ProductUpdate.status == status)

    total = await db.scalar(select(func.count(ProductUpdate.id)).where(*filters))
    result = await db.execute(
        select(ProductUpdate)
        .where(*filters)
        .order_by(
            # shipped 在前 (1), 非 shipped 在后 (0); 同档按 shipped_at/updated_at 倒序
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
    items: list[ProductUpdateResponse] = []
    for row in result.scalars().all():
        resp = ProductUpdateResponse.model_validate(row)
        if kind is not None and not any(e.kind == kind for e in resp.items):
            continue
        items.append(resp)

    # 注意: total 是 DB 计数, kind 过滤后 Python 端可能更少; 这里只对 status 精确
    return ProductUpdateListResponse(items=items, total=int(total or 0))


@router.post("/updates", response_model=ProductUpdateResponse, status_code=201)
async def create_product_update(
    data: ProductUpdateCreate,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
):
    shipped_at = data.shipped_at
    if data.status == ProductUpdateStatus.shipped and shipped_at is None:
        shipped_at = datetime.now(UTC)

    item = ProductUpdate(
        version=data.version,
        status=data.status,
        target_date=data.target_date,
        shipped_at=shipped_at,
        items=[entry.model_dump(mode="json") for entry in data.items],
        created_by_id=current_admin.id,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.patch("/updates/{update_id}", response_model=ProductUpdateResponse)
async def update_product_update(
    update_id: int,
    data: ProductUpdatePatch,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    item = await db.get(ProductUpdate, update_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product update not found")

    changes = data.model_dump(exclude_unset=True)
    if "version" in changes:
        item.version = changes["version"]
    if "status" in changes:
        item.status = changes["status"]
    if "target_date" in changes:
        item.target_date = changes["target_date"]
    if "items" in changes and changes["items"] is not None:
        item.items = changes["items"]
    if "shipped_at" in changes:
        item.shipped_at = changes["shipped_at"]
    if data.status == ProductUpdateStatus.shipped and item.shipped_at is None:
        item.shipped_at = datetime.now(UTC)
    if data.status is not None and data.status != ProductUpdateStatus.shipped and "shipped_at" not in changes:
        item.shipped_at = None
    item.updated_at = datetime.now(UTC)

    await db.flush()
    await db.refresh(item)
    return item


@router.delete("/updates/{update_id}", status_code=204)
async def delete_product_update(
    update_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """删除管理员在 DB 中创建的 ProductUpdate (builtin 不可删)."""
    if update_id <= 0:
        raise HTTPException(status_code=400, detail="Builtin updates cannot be deleted")
    item = await db.get(ProductUpdate, update_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product update not found")
    await db.delete(item)
    await db.flush()
