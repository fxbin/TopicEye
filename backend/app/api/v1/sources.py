from __future__ import annotations
import json
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import async_session
from app.core.database import get_db
from app.core.exceptions import NotFoundError
from app.models.user import User
from app.models.source import Source, SourceType, SourceStatus
from app.schemas.source import (
    SourceCreate,
    SourceUpdate,
    SourceResponse,
    SourceListResponse,
    SourceReorderRequest,
    SyncResultResponse,
    normalize_source_url_value,
    normalize_api_source_config_value,
)
from app.repositories.source_repo import SourceRepository
from app.services.content_pipeline import ingest_from_source
from app.api.v1._importers import (  # noqa: F401 — SourceBatchImportItem + _parse_source_batch re-exported for backward compat
    SourceBatchImportItem,
    SourceBatchImportRequest,
    _parse_source_batch,
    _preview_source_batch_items,
)
from app.services.plan_catalog import (
    plan_allows_private_source,
    private_sources_quota,
    private_sources_quota_exceeded,
)
from app.services.scrapers.recognizer import recognize_source_type
from app.services.source_cache import (
    SourceListCacheParams,
    get_cached_source_list,
    set_cached_source_list,
)
from app.services.source_read_cache import invalidate_source_read_caches

router = APIRouter(prefix="/sources", tags=["sources"])


def _invalidate_source_cache() -> None:
    invalidate_source_read_caches()


def _normalize_source_status(payload: dict, current: Source | None = None) -> dict:
    if payload.get("status") == SourceStatus.SYNCING:
        raise HTTPException(status_code=422, detail="syncing 是系统内部状态，不能手动设置")

    if payload.get("enabled") is False:
        payload["status"] = SourceStatus.DISABLED
        return payload

    if payload.get("status") == SourceStatus.DISABLED:
        payload["enabled"] = False
        return payload

    if payload.get("status") in {SourceStatus.ACTIVE, SourceStatus.ERROR}:
        payload.setdefault("enabled", True)

    if payload.get("enabled") is True and current is not None and current.status == SourceStatus.DISABLED:
        payload.setdefault("status", SourceStatus.ACTIVE)

    return payload


def _normalize_api_source_config(payload: dict, current: Source | None = None) -> dict:
    source_type = payload.get("source_type")
    if source_type is None and current is not None:
        source_type = current.source_type
    if source_type != SourceType.API:
        return payload

    keyword = payload.get("keyword")
    if keyword is None and current is not None:
        keyword = current.keyword
    try:
        normalized = normalize_api_source_config_value(keyword)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if normalized is not None or "keyword" in payload:
        payload["keyword"] = normalized
    return payload




@router.post("", response_model=SourceResponse, status_code=201, dependencies=[Depends(get_current_admin_user)])
async def create_source(data: SourceCreate, db: AsyncSession = Depends(get_db)):
    repo = SourceRepository(db)
    payload = data.model_dump()
    _normalize_source_status(payload)
    _normalize_api_source_config(payload)
    existing = await repo.get_one(Source.url == payload["url"])
    if existing:
        raise HTTPException(status_code=409, detail="信源 URL 已存在")
    if payload.get("sort_order") is None:
        max_order = await db.scalar(select(func.max(Source.sort_order)))
        payload["sort_order"] = (max_order or 0) + 10
    # Admin-created sources are public (system-scope)
    payload["owner_user_id"] = None
    payload["scope"] = "system"
    source = await repo.create(**payload)
    _invalidate_source_cache()
    return source


@router.get("", response_model=SourceListResponse)
async def list_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_type: str | None = None,
    status: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
):
    cache_params = SourceListCacheParams(
        page=page,
        page_size=page_size,
        source_type=source_type,
        status=status,
        enabled=enabled,
        keyword=keyword,
    )
    cached = get_cached_source_list(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "X-Sources-Cache": "HIT",
                "X-Sources-Cache-Age-Ms": str(int(age_seconds * 1000)),
            },
        )

    async with async_session() as db:
        stmt = select(Source).where(Source.scope == "system")
        count_stmt = select(func.count()).select_from(Source).where(Source.scope == "system")
        filters = []
        if source_type is not None:
            filters.append(Source.source_type == source_type)
        if status is not None:
            filters.append(Source.status == status)
        if enabled is not None:
            filters.append(Source.enabled == enabled)
        cleaned_keyword = keyword.strip() if keyword else ""
        if cleaned_keyword:
            pattern = f"%{cleaned_keyword}%"
            filters.append(
                or_(
                    Source.name.ilike(pattern),
                    Source.url.ilike(pattern),
                    Source.platform.ilike(pattern),
                    Source.category.ilike(pattern),
                    Source.keyword.ilike(pattern),
                )
            )
        for item_filter in filters:
            stmt = stmt.where(item_filter)
            count_stmt = count_stmt.where(item_filter)

        total = int(await db.scalar(count_stmt) or 0)
        result = await db.execute(
            stmt.order_by(Source.sort_order.asc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = list(result.scalars().all())
    payload = SourceListResponse(items=items, total=total, page=page, page_size=page_size).model_dump()
    content = set_cached_source_list(cache_params, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Sources-Cache": "MISS"},
    )


# ── /me series: user-owned private sources ─────────────────────────────
# Declared BEFORE /{source_id} routes so FastAPI matches the literal
# "me" segment before the {source_id} path parameter.


@router.get("/me", response_model=SourceListResponse)
async def list_my_sources(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    source_type: str | None = None,
    status: str | None = None,
    enabled: bool | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
):
    cache_params = SourceListCacheParams(
        page=page,
        page_size=page_size,
        source_type=source_type,
        status=status,
        enabled=enabled,
        keyword=keyword,
        user_id=current_user.id,
    )
    cached = get_cached_source_list(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "X-Sources-Cache": "HIT",
                "X-Sources-Cache-Age-Ms": str(int(age_seconds * 1000)),
            },
        )

    async with async_session() as db:
        stmt = select(Source).where(Source.owner_user_id == current_user.id)
        count_stmt = select(func.count()).select_from(Source).where(Source.owner_user_id == current_user.id)
        # 未过滤的私有信源总数，用于配额展示（total 是过滤后分页计数，不能直接复用）
        private_sources_used = int(await db.scalar(count_stmt) or 0)
        filters = []
        if source_type is not None:
            filters.append(Source.source_type == source_type)
        if status is not None:
            filters.append(Source.status == status)
        if enabled is not None:
            filters.append(Source.enabled == enabled)
        cleaned_keyword = keyword.strip() if keyword else ""
        if cleaned_keyword:
            pattern = f"%{cleaned_keyword}%"
            filters.append(
                or_(
                    Source.name.ilike(pattern),
                    Source.url.ilike(pattern),
                    Source.platform.ilike(pattern),
                    Source.category.ilike(pattern),
                    Source.keyword.ilike(pattern),
                )
            )
        for item_filter in filters:
            stmt = stmt.where(item_filter)
            count_stmt = count_stmt.where(item_filter)

        total = int(await db.scalar(count_stmt) or 0)
        result = await db.execute(
            stmt.order_by(Source.sort_order.asc()).offset((page - 1) * page_size).limit(page_size)
        )
        items = list(result.scalars().all())
    payload = SourceListResponse(items=items, total=total, page=page, page_size=page_size, private_sources_used=private_sources_used, private_sources_quota=private_sources_quota(current_user.plan)).model_dump()
    content = set_cached_source_list(cache_params, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Sources-Cache": "MISS"},
    )


@router.get("/me/recognize")
async def recognize_my_source_url(
    url: str = Query(..., min_length=3, max_length=2048, description="用户粘贴的信源 URL"),
    name: str | None = Query(None, description="可选信源名，辅助识别 handle"),
    current_user: User = Depends(get_current_user),
):
    """根据粘贴的 URL 推断信源类型 + 规范化 URL + extra_config。

    前端在创建私有信源时，粘贴 URL 后调此端点自动填充 source_type 字段。
    不消耗配额、不创建任何记录——纯识别辅助。
    """
    try:
        source_type, normalized_url, extra_config = recognize_source_type(url, name=name)
    except Exception:
        # 识别失败不报错，兜底返回 RSS（让用户自己确认）
        return {"source_type": "RSS", "normalized_url": url, "extra_config": None}
    return {
        "source_type": source_type.value if hasattr(source_type, "value") else str(source_type),
        "normalized_url": normalized_url,
        "extra_config": extra_config,
    }


@router.post("/me", response_model=SourceResponse, status_code=201)
async def create_my_source(
    data: SourceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="私有信源需要 Pro 及以上套餐")
    # 配额检查：在去重/创建前拦截，避免无效写入
    current_count = int(
        await db.scalar(
            select(func.count()).select_from(Source).where(Source.owner_user_id == current_user.id)
        )
        or 0
    )
    if private_sources_quota_exceeded(current_user.plan, current_count):
        quota = private_sources_quota(current_user.plan)
        raise HTTPException(
            status_code=403,
            detail=f"私有信源已达上限（{current_count}/{quota}），请升级套餐或删除不再使用的信源",
        )
    repo = SourceRepository(db)
    payload = data.model_dump()
    _normalize_source_status(payload)
    _normalize_api_source_config(payload)
    existing = await repo.get_one(Source.url == payload["url"])
    if existing:
        raise HTTPException(status_code=409, detail="信源 URL 已存在")
    if payload.get("sort_order") is None:
        max_order = await db.scalar(select(func.max(Source.sort_order)))
        payload["sort_order"] = (max_order or 0) + 10
    # Force owner + scope — never trust client input for these
    payload["owner_user_id"] = current_user.id
    payload["scope"] = "user"
    source = await repo.create(**payload)
    _invalidate_source_cache()
    return source


@router.get("/me/{source_id}", response_model=SourceResponse)
async def get_my_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = SourceRepository(db)
    # Double owner check: must exist AND belong to current user; otherwise mask as 404
    existing = await repo.get_one(
        Source.id == source_id,
        Source.owner_user_id == current_user.id,
    )
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return existing


@router.put("/me/{source_id}", response_model=SourceResponse)
async def update_my_source(
    source_id: int,
    data: SourceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = SourceRepository(db)
    try:
        existing = await repo.get_by_id_or_raise(source_id, resource_name="Source")
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    if existing.owner_user_id != current_user.id:
        # Mask as 404 to avoid leaking existence
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    try:
        payload = data.model_dump(exclude_unset=True)
        _normalize_source_status(payload, existing)
        _normalize_api_source_config(payload, existing)
        if "url" in payload:
            url_existing = await repo.get_one(Source.url == payload["url"])
            if url_existing and url_existing.id != source_id:
                raise HTTPException(status_code=409, detail="信源 URL 已存在")
        # Force owner + scope — never drift from /me invariants
        payload["owner_user_id"] = current_user.id
        payload["scope"] = "user"
        source = await repo.update(source_id, **payload)
        _invalidate_source_cache()
        return source
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/me/{source_id}", status_code=204)
async def delete_my_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = SourceRepository(db)
    try:
        existing = await repo.get_by_id_or_raise(source_id, resource_name="Source")
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    if existing.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    try:
        await repo.delete(source_id)
        _invalidate_source_cache()
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/me/{source_id}/sync", response_model=SyncResultResponse)
async def sync_my_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = SourceRepository(db)
    try:
        existing = await repo.get_by_id_or_raise(source_id, resource_name="Source")
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    if existing.owner_user_id != current_user.id:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    if not existing.enabled or existing.status == SourceStatus.DISABLED:
        raise HTTPException(status_code=409, detail="信源已禁用，请启用后再同步")

    source = await repo.claim_sync(
        source_id,
        lease_seconds=int(settings.SOURCE_SYNC_TIMEOUT_SECONDS),
    )
    await db.commit()
    if source is None:
        raise HTTPException(status_code=409, detail="信源正在同步中，请稍后再试")

    stats = await ingest_from_source(source, db)
    await db.refresh(source)
    _invalidate_source_cache()
    if source.status == SourceStatus.ERROR or source.sync_error:
        await db.commit()
        raise HTTPException(status_code=502, detail=source.sync_error or "信源同步失败")
    from app._post_sync_pipeline import _request_post_sync_pipeline

    _request_post_sync_pipeline(stats)
    return SyncResultResponse(
        fetched=stats["fetched"],
        new=stats["new"],
        duplicates=stats["duplicates"],
        source_info=SourceResponse.model_validate(source),
    )


@router.post("/reorder", dependencies=[Depends(get_current_admin_user)])
async def reorder_sources(data: SourceReorderRequest, db: AsyncSession = Depends(get_db)):
    """Persist source order for one kanban lane or the current ordered subset."""
    unique_ids = list(dict.fromkeys(data.ordered_ids))
    if not unique_ids:
        raise HTTPException(status_code=400, detail="ordered_ids cannot be empty")

    # Admin reorder only touches system-scope sources
    result = await db.execute(select(Source).where(Source.id.in_(unique_ids), Source.scope == "system"))
    sources_by_id = {source.id: source for source in result.scalars().all()}
    missing_ids = [source_id for source_id in unique_ids if source_id not in sources_by_id]
    if missing_ids:
        raise HTTPException(status_code=404, detail=f"Sources not found: {missing_ids}")

    for index, source_id in enumerate(unique_ids):
        sources_by_id[source_id].sort_order = (index + 1) * 10

    await db.flush()
    _invalidate_source_cache()
    return {"message": "信源顺序已保存", "updated": len(unique_ids)}


@router.post("/import-opml", dependencies=[Depends(get_current_admin_user)])
async def import_opml(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import RSS feeds from OPML file."""
    content = await file.read()
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        raise HTTPException(status_code=400, detail="Invalid OPML XML")

    body = root.find("body")
    if body is None:
        raise HTTPException(status_code=400, detail="No <body> element found in OPML")

    outlines = body.findall(".//outline[@xmlUrl]")
    repo = SourceRepository(db)
    created = skipped = 0

    for outline in outlines:
        try:
            feed_url = normalize_source_url_value(outline.get("xmlUrl", ""))
        except ValueError:
            continue
        existing = await repo.get_one(Source.url == feed_url)
        if existing:
            skipped += 1
            continue

        name = outline.get("title") or outline.get("text") or feed_url

        # URL -> source_type auto-detection (T1-3b): replaces the hard-coded
        # xgo.ing branch and adds YouTube / Podcast / Newsletter recognition.
        source_type, normalized_url, extra_config = recognize_source_type(feed_url, name=name)
        keyword = json.dumps(extra_config) if extra_config else None

        await repo.create(
            name=name,
            url=feed_url,
            source_type=source_type,
            category="导入",
            owner_user_id=None,
            scope="system",
            enabled=True,
            status=SourceStatus.ACTIVE,
            keyword=keyword,
        )
        created += 1

    _invalidate_source_cache()
    return {
        "created": created,
        "skipped": skipped,
        "total": len(outlines),
        "message": f"成功导入 {created} 个源，跳过 {skipped} 个重复。",
    }


@router.post("/preview-batch", dependencies=[Depends(get_current_admin_user)])
async def preview_source_batch(
    data: SourceBatchImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Preview JSON/Markdown/OPML source config before importing."""
    items = await _preview_source_batch_items(db, data.content, data.category)
    return {
        "items": items,
        "total": len(items),
        "duplicates": sum(1 for item in items if item.duplicate),
        "importable": sum(1 for item in items if not item.duplicate),
    }


@router.post("/import-batch", dependencies=[Depends(get_current_admin_user)])
async def import_source_batch(
    data: SourceBatchImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """Import sources from JSON/Markdown/OPML text."""
    items = await _preview_source_batch_items(db, data.content, data.category)
    repo = SourceRepository(db)
    max_order = await db.scalar(select(func.max(Source.sort_order)))
    next_order = (max_order or 0) + 10
    created = skipped = 0

    for item in items:
        if item.duplicate:
            skipped += 1
            continue
        try:
            source_type = SourceType(item.source_type)
        except ValueError:
            source_type = SourceType.RSS
        await repo.create(
            name=item.name,
            url=item.url,
            source_type=source_type,
            category=item.category,
            platform=item.platform,
            weight=data.weight,
            sort_order=next_order,
            owner_user_id=None,
            scope="system",
            enabled=data.enabled,
            status=SourceStatus.ACTIVE if data.enabled else SourceStatus.DISABLED,
        )
        next_order += 10
        created += 1

    _invalidate_source_cache()
    return {
        "created": created,
        "skipped": skipped,
        "total": len(items),
        "message": f"成功导入 {created} 个信源，跳过 {skipped} 个重复。",
    }


@router.get("/{source_id}", response_model=SourceResponse, dependencies=[Depends(get_current_admin_user)])
async def get_source(source_id: int, db: AsyncSession = Depends(get_db)):
    repo = SourceRepository(db)
    # Admin can only see system-scope sources
    try:
        existing = await repo.get_one(Source.id == source_id, Source.scope == "system")
    except Exception:
        existing = None
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    return existing


@router.put("/{source_id}", response_model=SourceResponse, dependencies=[Depends(get_current_admin_user)])
async def update_source(source_id: int, data: SourceUpdate, db: AsyncSession = Depends(get_db)):
    repo = SourceRepository(db)
    # Admin can only update system-scope sources
    current = await repo.get_one(Source.id == source_id, Source.scope == "system")
    if current is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    try:
        payload = data.model_dump(exclude_unset=True)
        _normalize_source_status(payload, current)
        _normalize_api_source_config(payload, current)
        if "url" in payload:
            existing = await repo.get_one(Source.url == payload["url"])
            if existing and existing.id != source_id:
                raise HTTPException(status_code=409, detail="信源 URL 已存在")
        # Lock owner + scope to system for admin updates
        payload["owner_user_id"] = None
        payload["scope"] = "system"
        source = await repo.update(source_id, **payload)
        _invalidate_source_cache()
        return source
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.delete("/{source_id}", status_code=204, dependencies=[Depends(get_current_admin_user)])
async def delete_source(source_id: int, db: AsyncSession = Depends(get_db)):
    repo = SourceRepository(db)
    # Admin can only delete system-scope sources
    existing = await repo.get_one(Source.id == source_id, Source.scope == "system")
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")
    try:
        await repo.delete(source_id)
        _invalidate_source_cache()
    except NotFoundError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)


@router.post("/{source_id}/sync", response_model=SyncResultResponse, dependencies=[Depends(get_current_admin_user)])
async def sync_source(source_id: int, db: AsyncSession = Depends(get_db)):
    repo = SourceRepository(db)
    # Admin can only sync system-scope sources
    existing = await repo.get_one(Source.id == source_id, Source.scope == "system")
    if existing is None:
        raise HTTPException(status_code=404, detail=f"Source {source_id} not found")

    if not existing.enabled or existing.status == SourceStatus.DISABLED:
        raise HTTPException(status_code=409, detail="信源已禁用，请启用后再同步")

    source = await repo.claim_sync(
        source_id,
        lease_seconds=int(settings.SOURCE_SYNC_TIMEOUT_SECONDS),
    )
    await db.commit()
    if source is None:
        raise HTTPException(status_code=409, detail="信源正在同步中，请稍后再试")

    stats = await ingest_from_source(source, db)
    await db.refresh(source)
    _invalidate_source_cache()
    if source.status == SourceStatus.ERROR or source.sync_error:
        await db.commit()
        raise HTTPException(status_code=502, detail=source.sync_error or "信源同步失败")
    from app._post_sync_pipeline import _request_post_sync_pipeline

    _request_post_sync_pipeline(stats)
    return SyncResultResponse(
        fetched=stats["fetched"],
        new=stats["new"],
        duplicates=stats["duplicates"],
        source_info=SourceResponse.model_validate(source),
    )
