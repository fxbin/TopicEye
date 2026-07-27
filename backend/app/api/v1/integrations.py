from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.models.user import User
from app.schemas.integration import (
    IntegrationStatusResponse,
    IntegrationUpdateRequest,
    WeReadBestBookmarksResponse,
    WeReadBookInfo,
    WeReadReadDataResponse,
    WeReadSearchResponse,
    WeReadShelfSyncResponse,
    WeReadSyncResponse,
)
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
from app.services.weread_materials import (
    get_or_fetch_weread_readdata,
    get_or_fetch_weread_shelf,
    get_weread_bestbookmarks,
    get_weread_book_info,
    redact_weread_sync_error,
    search_weread_books,
    sync_weread_materials,
)

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
    limit: int = Query(0, ge=0, le=1000, description="最大拉取条数，0=全量同步"),
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
        raise HTTPException(status_code=502, detail=detail) from exc
    except Exception as exc:
        if claimed.last_sync_status == "syncing":
            await mark_user_integration_sync_error(db, claimed, message=redact_weread_sync_error(str(exc), api_key))
        await db.commit()
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=f"微信读书素材同步失败：{detail}") from exc

    return WeReadSyncResponse(
        fetched=int(result["fetched"]),
        new=int(result["new"]),
        duplicates=int(result["duplicates"]),
        updated=int(result.get("updated", 0)),
        source_name=str(result["source_name"]),
        message=f"同步完成：拉取 {result['fetched']} 条，新增 {result['new']} 条，更新 {result.get('updated', 0)} 条。",
    )


# ── WeRead 搜索 ──


async def _get_weread_api_key(
    current_user: User,
    db: AsyncSession,
) -> str:
    """获取当前用户的 WeRead API Key，未配置时抛 422。"""
    integration = await get_user_integration(db, user_id=current_user.id, provider=WEREAD_PROVIDER)
    api_key = integration_api_key(integration)
    if not integration or not api_key:
        raise HTTPException(status_code=422, detail="请先在个人中心配置微信读书 API Key")
    return api_key


@router.get("/weread/search", response_model=WeReadSearchResponse)
async def search_weread(
    keyword: str = Query(..., min_length=1, max_length=100, description="搜索关键词"),
    count: int = Query(10, ge=1, le=30, description="每页数量"),
    scope: int = Query(10, ge=0, le=20, description="搜索类型：0=全部, 10=电子书, 14=听书, 6=作者, 12=全文, 13=书单"),
    max_idx: int = Query(0, ge=0, le=200, description="翻页偏移"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """搜索微信读书书库（不限于书架内的书）。"""
    api_key = await _get_weread_api_key(current_user, db)
    try:
        result = await search_weread_books(api_key, keyword, count=count, scope=scope, max_idx=max_idx)
    except RuntimeError as exc:
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return WeReadSearchResponse(
        books=result["books"],
        hasMore=result["hasMore"],
        total=result["total"],
        keyword=keyword,
    )


@router.get("/weread/book/{book_id}", response_model=WeReadBookInfo)
async def get_weread_book(
    book_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取微信读书书籍详情。"""
    api_key = await _get_weread_api_key(current_user, db)
    try:
        result = await get_weread_book_info(api_key, book_id)
    except RuntimeError as exc:
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return WeReadBookInfo(**result)


# ── WeRead 阅读统计 / 热门划线 / 完整书架 ──


@router.get("/weread/readdata", response_model=WeReadReadDataResponse)
async def get_weread_readdata(
    read_type: str = Query("all", description="统计周期：all/week/month/year"),
    force_refresh: bool = Query(False, description="强制刷新缓存，绕过 TTL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取微信读书阅读统计数据（时长/天数/排行/偏好）。

    优先从本地缓存读取（TTL 24h），缓存不存在或过期时回源拉取并写入缓存。
    传入 ``force_refresh=true`` 可强制绕过缓存重新拉取。
    """
    api_key = await _get_weread_api_key(current_user, db)
    try:
        result = await get_or_fetch_weread_readdata(
            db, api_key, user_id=current_user.id, read_type=read_type, force_refresh=force_refresh
        )
    except RuntimeError as exc:
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Strip cache metadata before response validation
    result.pop("_cached_at", None)
    result.pop("_stale", None)
    return WeReadReadDataResponse(**result)


@router.get("/weread/book/{book_id}/bookmarks", response_model=WeReadBestBookmarksResponse)
async def get_weread_bookmarks(
    book_id: str,
    count: int = Query(20, ge=1, le=20, description="最大返回条数"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取书籍热门划线（按热度排序，最多 20 条）。"""
    api_key = await _get_weread_api_key(current_user, db)
    try:
        result = await get_weread_bestbookmarks(api_key, book_id, count=count)
    except RuntimeError as exc:
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return WeReadBestBookmarksResponse(**result)


@router.get("/weread/shelf", response_model=WeReadShelfSyncResponse)
async def get_weread_shelf(
    force_refresh: bool = Query(False, description="强制刷新缓存，绕过 TTL"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取完整书架（含未读/听书），用于书架 vs 笔记本对比分析。

    优先从本地缓存读取（TTL 24h），缓存不存在或过期时回源拉取并写入缓存。
    传入 ``force_refresh=true`` 可强制绕过缓存重新拉取。
    """
    api_key = await _get_weread_api_key(current_user, db)
    try:
        result = await get_or_fetch_weread_shelf(
            db, api_key, user_id=current_user.id, force_refresh=force_refresh
        )
    except RuntimeError as exc:
        detail = redact_weread_sync_error(str(exc), api_key)
        raise HTTPException(status_code=502, detail=detail) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Strip cache metadata before response validation
    result.pop("_cached_at", None)
    result.pop("_stale", None)
    return WeReadShelfSyncResponse(**result)
