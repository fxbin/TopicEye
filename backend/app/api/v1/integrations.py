from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.integration import IntegrationStatusResponse, IntegrationUpdateRequest, WeReadSyncResponse
from app.services.integration_service import (
    WEREAD_PROVIDER,
    claim_user_integration_sync,
    clear_user_integration,
    get_user_integration,
    integration_api_key,
    integration_status,
    mark_user_integration_sync_error,
    upsert_user_integration,
)
from app.services.weread_materials import redact_weread_sync_error, sync_weread_materials

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/weread", response_model=IntegrationStatusResponse)
async def get_weread_integration(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    integration = await get_user_integration(db, user_id=current_user.id, provider=WEREAD_PROVIDER)
    return integration_status(integration, WEREAD_PROVIDER)


@router.put("/weread", response_model=IntegrationStatusResponse)
async def update_weread_integration(
    data: IntegrationUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    integration = await upsert_user_integration(
        db,
        user_id=current_user.id,
        provider=WEREAD_PROVIDER,
        api_key=data.api_key,
        config=data.config,
    )
    return integration_status(integration, WEREAD_PROVIDER)


@router.delete("/weread", response_model=IntegrationStatusResponse)
async def delete_weread_integration(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await clear_user_integration(db, user_id=current_user.id, provider=WEREAD_PROVIDER)
    return integration_status(None, WEREAD_PROVIDER)


@router.post("/weread/sync", response_model=WeReadSyncResponse)
async def sync_weread(
    limit: int = Query(50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    integration = await get_user_integration(db, user_id=current_user.id, provider=WEREAD_PROVIDER)
    api_key = integration_api_key(integration)
    if not integration or not api_key:
        raise HTTPException(status_code=422, detail="请先在个人中心配置微信读书 API Key")

    await db.commit()
    claimed = await claim_user_integration_sync(
        db,
        integration_id=integration.id,
        lease_seconds=int(settings.SOURCE_SYNC_TIMEOUT_SECONDS),
    )
    await db.commit()
    if claimed is None:
        raise HTTPException(status_code=409, detail="微信读书素材正在同步中，请稍后再试")

    try:
        result = await sync_weread_materials(db, claimed, user_id=current_user.id, api_key=api_key, limit=limit)
    except RuntimeError as exc:
        if claimed.last_sync_status == "syncing":
            await mark_user_integration_sync_error(db, claimed, message=redact_weread_sync_error(str(exc), api_key))
        await db.commit()
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail)
    except Exception as exc:
        if claimed.last_sync_status == "syncing":
            await mark_user_integration_sync_error(db, claimed, message=redact_weread_sync_error(str(exc), api_key))
        await db.commit()
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=f"微信读书素材同步失败：{detail}")

    return WeReadSyncResponse(
        fetched=int(result["fetched"]),
        new=int(result["new"]),
        duplicates=int(result["duplicates"]),
        source_name=str(result["source_name"]),
        message=f"同步完成：拉取 {result['fetched']} 条，新增 {result['new']} 条。",
    )
