from __future__ import annotations

import hashlib

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.favorite import FavoriteStatus, FavoriteTargetType
from app.models.user import User
from app.repositories.favorite_repo import FavoriteRepo
from app.schemas.favorite import (
    FavoriteBoardReorderRequest,
    FavoriteBulkDeleteRequest,
    FavoriteBulkStatusRequest,
    FavoriteCreate,
    FavoriteListResponse,
    FavoriteReorderRequest,
    FavoriteResponse,
    FavoriteUpdate,
)
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.favorite_cache import (
    favorite_to_dict,
    get_cached_json,
    invalidate_favorite_cache,
    set_cached_json,
)
from app.services.json_cache import invalidate_json_cache

router = APIRouter(prefix="/favorites", tags=["favorites"])
MAX_FAVORITE_STATE_TARGETS = 200
MAX_FAVORITE_STATE_TARGET_KEY_LENGTH = 255


def _invalidate_favorite_mutation_caches(*, content_changed: bool = False) -> None:
    invalidate_favorite_cache()
    invalidate_json_cache("contents:favorites:")
    if content_changed:
        invalidate_content_read_caches()


def _favorite_cache_hit_response(content: bytes, age_seconds: float) -> Response:
    return Response(
        content=content,
        media_type="application/json",
        headers={
            "X-Favorites-Cache": "HIT",
            "X-Favorites-Cache-Age-Ms": str(round(age_seconds * 1000, 3)),
        },
    )


def _parse_state_target_ids(raw_target_ids: str | None) -> list[int]:
    if not raw_target_ids:
        return []
    ids: list[int] = []
    for item in raw_target_ids.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ids.append(int(value))
        except ValueError:
            raise HTTPException(status_code=422, detail="target_ids must be comma-separated integers") from None
    return ids


def _parse_state_target_keys(raw_target_keys: str | None) -> list[str]:
    if not raw_target_keys:
        return []
    return [item.strip() for item in raw_target_keys.split(",") if item.strip()]


def _normalize_state_target_keys(
    target_type: FavoriteTargetType,
    *,
    target_ids: str | None,
    target_keys: str | None,
) -> list[str]:
    keys = _parse_state_target_keys(target_keys)
    keys.extend(
        FavoriteRepo.make_target_key(target_type, target_id=target_id)
        for target_id in _parse_state_target_ids(target_ids)
    )
    normalized = sorted(set(keys))
    if any(len(key) > MAX_FAVORITE_STATE_TARGET_KEY_LENGTH for key in normalized):
        raise HTTPException(
            status_code=422,
            detail=f"favorites state target key length must be <= {MAX_FAVORITE_STATE_TARGET_KEY_LENGTH}",
        )
    if len(normalized) > MAX_FAVORITE_STATE_TARGETS:
        raise HTTPException(
            status_code=422,
            detail=f"favorites state target count must be <= {MAX_FAVORITE_STATE_TARGETS}",
        )
    return normalized


def _favorite_state_cache_key(user_id: int, target_type: FavoriteTargetType, target_keys: list[str]) -> str:
    digest = hashlib.sha256("\n".join(target_keys).encode("utf-8")).hexdigest()
    return f"user:{user_id}:state:{target_type.value}:{digest}"


@router.get("", response_model=FavoriteListResponse)
async def list_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    target_type: FavoriteTargetType | None = None,
    status: FavoriteStatus | None = None,
    keyword: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    cache_key = f"user:{current_user.id}:list:{page}:{page_size}:{target_type or ''}:{status or ''}:{keyword or ''}"
    cached = get_cached_json(cache_key)
    if cached:
        content, age_seconds = cached
        return _favorite_cache_hit_response(content, age_seconds)

    items, total = await FavoriteRepo(db, current_user.id).list_paginated(
        page=page,
        page_size=page_size,
        target_type=target_type,
        status=status,
        keyword=keyword,
    )
    payload = {
        "items": [favorite_to_dict(item) for item in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    content = set_cached_json(cache_key, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Favorites-Cache": "MISS"},
    )


@router.post("", response_model=FavoriteResponse, status_code=201)
async def create_favorite(
    data: FavoriteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FavoriteRepo(db, current_user.id)
    try:
        item = await repo.upsert(data)
        _invalidate_favorite_mutation_caches(content_changed=data.target_type == FavoriteTargetType.CONTENT)
        return item
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/state")
async def favorite_state(
    target_type: FavoriteTargetType,
    target_ids: str | None = Query(None, description="Comma-separated target IDs"),
    target_keys: str | None = Query(None, description="Comma-separated target keys"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    keys = _normalize_state_target_keys(
        target_type,
        target_ids=target_ids,
        target_keys=target_keys,
    )
    cache_key = _favorite_state_cache_key(current_user.id, target_type, keys)
    cached = get_cached_json(cache_key)
    if cached:
        content, age_seconds = cached
        return _favorite_cache_hit_response(content, age_seconds)

    state_items = await FavoriteRepo(db, current_user.id).state_for_targets(
        target_type,
        target_keys=keys,
    )
    payload = {"items": state_items}
    content = set_cached_json(cache_key, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Favorites-Cache": "MISS"},
    )


@router.post("/reorder", response_model=list[FavoriteResponse])
async def reorder_favorites(
    data: FavoriteReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        items = await FavoriteRepo(db, current_user.id).reorder_status(status=data.status, ordered_ids=data.ordered_ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _invalidate_favorite_mutation_caches()
    return items


@router.post("/reorder-board", response_model=list[FavoriteResponse])
async def reorder_favorite_board(
    data: FavoriteBoardReorderRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        items = await FavoriteRepo(db, current_user.id).reorder_board(
            [(column.status, column.ordered_ids) for column in data.columns]
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _invalidate_favorite_mutation_caches()
    return items


@router.post("/bulk-status", response_model=list[FavoriteResponse])
async def bulk_update_favorite_status(
    data: FavoriteBulkStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        items = await FavoriteRepo(db, current_user.id).bulk_update_status(status=data.status, ids=data.ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _invalidate_favorite_mutation_caches()
    return items


@router.post("/bulk-delete")
async def bulk_delete_favorites(
    data: FavoriteBulkDeleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FavoriteRepo(db, current_user.id)
    content_changed = False
    for favorite_id in data.ids:
        item = await repo.get_by_id(favorite_id)
        if item is not None and item.target_type == FavoriteTargetType.CONTENT:
            content_changed = True
            break
    try:
        deleted = await repo.bulk_delete(data.ids)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    _invalidate_favorite_mutation_caches(content_changed=content_changed)
    return {"deleted": deleted}


@router.patch("/{favorite_id}", response_model=FavoriteResponse)
async def update_favorite(
    favorite_id: int,
    data: FavoriteUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    item = await FavoriteRepo(db, current_user.id).update(favorite_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Favorite not found")
    _invalidate_favorite_mutation_caches()
    return item


@router.delete("/{favorite_id}")
async def delete_favorite(
    favorite_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    repo = FavoriteRepo(db, current_user.id)
    item = await repo.get_by_id(favorite_id)
    deleted = await repo.delete(favorite_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Favorite not found")
    _invalidate_favorite_mutation_caches(
        content_changed=item is not None and item.target_type == FavoriteTargetType.CONTENT
    )
    return {"deleted": True}
