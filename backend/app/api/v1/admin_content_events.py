"""Administrative controls for content-event normalization and review."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.schemas.content_event import (
    ContentEventCanonicalRequest,
    ContentEventMutationResponse,
    ContentEventNormalizeRequest,
    ContentEventNormalizeResponse,
    ContentEventReviewListResponse,
    ContentEventReviewRequest,
    ContentEventUnlockCanonicalRequest,
)
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventNotFoundError,
    ContentEventService,
    ContentEventValidationError,
)

router = APIRouter(
    prefix="/admin/content-events",
    tags=["admin-content-events"],
    dependencies=[Depends(get_current_admin_user)],
)


def _raise_domain_http(exc: Exception) -> None:
    if isinstance(exc, ContentEventNotFoundError):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc) or "Content event not found",
        ) from exc
    if isinstance(exc, ContentEventConflictError):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc) or "Content event conflict",
        ) from exc
    if isinstance(exc, ContentEventValidationError):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc) or "Invalid content event operation",
        ) from exc
    raise exc


def _mutation_response(group: Any) -> ContentEventMutationResponse:
    return ContentEventMutationResponse(
        event_id=group.id,
        version=group.version,
        canonical_content_id=group.canonical_content_id,
        canonical_locked=group.canonical_locked,
    )


@router.post(
    "/normalize",
    response_model=ContentEventNormalizeResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def normalize_content_events(
    data: ContentEventNormalizeRequest,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=1,
        max_length=200,
    ),
    admin_user: Any = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ContentEventNormalizeResponse:
    """Start one leased, idempotent normalization pass."""

    if not idempotency_key.strip():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Idempotency-Key must not be blank",
        )

    from app.services.content_event_normalization import (
        normalize_recent_events_with_lease,
    )

    try:
        result = await normalize_recent_events_with_lease(
            db,
            hours=data.hours,
            mode=data.mode,
            owner_user_id=data.owner_user_id,
            idempotency_key=idempotency_key,
        )
        await db.commit()
    except (
        ContentEventNotFoundError,
        ContentEventConflictError,
        ContentEventValidationError,
    ) as exc:
        _raise_domain_http(exc)

    return ContentEventNormalizeResponse(
        idempotency_key=idempotency_key,
        mode=data.mode,
        scope=data.scope,
        owner_user_id=data.owner_user_id,
        result=result,
    )


@router.get(
    "/reviews",
    response_model=ContentEventReviewListResponse,
)
async def list_content_event_reviews(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    review_status: str = Query(
        "pending",
        pattern=r"^(pending|auto|confirmed|rejected)$",
    ),
    db: AsyncSession = Depends(get_db),
) -> ContentEventReviewListResponse:
    result = await ContentEventService(db).list_reviews(
        page=page,
        page_size=page_size,
        review_status=review_status,
    )
    return ContentEventReviewListResponse.model_validate(result)


@router.patch(
    "/members/{member_id}/review",
    response_model=ContentEventMutationResponse,
)
async def review_content_event_member(
    member_id: int,
    data: ContentEventReviewRequest,
    admin_user: Any = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ContentEventMutationResponse:
    service = ContentEventService(db)
    try:
        group = await service.review_relation(
            member_id,
            decision=data.decision,
            relation_type=data.relation_type,
            reason=data.reason.strip(),
            expected_version=data.expected_version,
            reviewer_user_id=admin_user.id,
        )
        await db.commit()
    except (
        ContentEventNotFoundError,
        ContentEventConflictError,
        ContentEventValidationError,
    ) as exc:
        _raise_domain_http(exc)
    return _mutation_response(group)


@router.put(
    "/{event_id}/canonical",
    response_model=ContentEventMutationResponse,
)
async def set_content_event_canonical(
    event_id: int,
    data: ContentEventCanonicalRequest,
    admin_user: Any = Depends(get_current_admin_user),
    db: AsyncSession = Depends(get_db),
) -> ContentEventMutationResponse:
    service = ContentEventService(db)
    try:
        group = await service.set_canonical(
            event_id,
            data.canonical_content_id,
            former_canonical_relation_type=data.former_canonical_relation_type,
            reason=data.reason.strip(),
            expected_version=data.expected_version,
            actor_user_id=admin_user.id,
        )
        await db.commit()
    except (
        ContentEventNotFoundError,
        ContentEventConflictError,
        ContentEventValidationError,
    ) as exc:
        _raise_domain_http(exc)
    return _mutation_response(group)


@router.post(
    "/{event_id}/unlock-canonical",
    response_model=ContentEventMutationResponse,
)
async def unlock_content_event_canonical(
    event_id: int,
    data: ContentEventUnlockCanonicalRequest,
    db: AsyncSession = Depends(get_db),
) -> ContentEventMutationResponse:
    service = ContentEventService(db)
    try:
        group = await service.unlock_canonical(
            event_id,
            reason=(data.reason or "manual unlock").strip(),
            expected_version=data.expected_version,
        )
        await db.commit()
    except (
        ContentEventNotFoundError,
        ContentEventConflictError,
        ContentEventValidationError,
    ) as exc:
        _raise_domain_http(exc)
    return _mutation_response(group)
