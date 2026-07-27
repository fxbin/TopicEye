from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user, get_optional_current_user
from app.core.database import get_db
from app.models.product_feedback import (
    IssueFeedback,
    IssueFeedbackStatus,
    ProductUpdate,
    ProductUpdateKind,
    ProductUpdateStatus,
)
from app.models.user import User
from app.repositories.product_feedback_repo import (
    IssueFeedbackRepository,
    ProductUpdateRepository,
)
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
    IssueFeedbackRepository(db).add_instance(issue)
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
    repo = IssueFeedbackRepository(db)
    total = await repo.count_user_issues(user_id=current_user.id, status=status)
    items_rows = await repo.list_user_issues(
        user_id=current_user.id,
        status=status,
        limit=limit,
        offset=offset,
    )
    items = [_issue_response(issue, current_user) for issue in items_rows]
    open_count, fixed_count = await repo.count_issues_by_status(user_id=current_user.id)
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
    repo = IssueFeedbackRepository(db)
    total = await repo.count_all_issues(status=status, severity=severity, area=area)
    rows = await repo.list_all_issues_with_reporter(
        status=status,
        severity=severity,
        area=area,
        limit=limit,
        offset=offset,
    )
    items = [_issue_response(issue, reporter) for issue, reporter in rows]
    open_count, fixed_count = await repo.count_issues_by_status()
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
    repo = IssueFeedbackRepository(db)
    row = await repo.get_issue_with_reporter(issue_id)
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
    repo = ProductUpdateRepository(db)
    total = await repo.count_updates(status=status)
    rows = await repo.list_updates(status=status, limit=limit, offset=offset)

    items: list[ProductUpdateResponse] = []
    for row in rows:
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
    ProductUpdateRepository(db).add_instance(item)
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
    item = await ProductUpdateRepository(db).get_by_id(update_id)
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
    repo = ProductUpdateRepository(db)
    item = await repo.get_by_id(update_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Product update not found")
    await repo.delete_instance(item)
