"""Public read API for canonical content events."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_optional_current_user
from app.core.database import get_db
from app.schemas.content_event import ContentEventCoverageLookupResponse, ContentEventLookupResponse
from app.services.content_event_coverage import get_event_coverage
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventNotFoundError,
    ContentEventService,
)

router = APIRouter(prefix="/contents", tags=["content-events"])


@router.get(
    "/{content_id}/event",
    response_model=ContentEventLookupResponse,
)
async def get_content_event(
    content_id: int,
    member_limit: int = Query(20, ge=1, le=100),
    member_offset: int = Query(0, ge=0),
    current_user: Any | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContentEventLookupResponse:
    """Return the visible event for a content item, if it was normalized."""

    service = ContentEventService(db)
    try:
        event = await service.get_event_detail(
            content_id,
            visible_user_id=current_user.id if current_user is not None else None,
            member_limit=member_limit,
            member_offset=member_offset,
        )
    except ContentEventNotFoundError as exc:
        # Missing and non-visible content intentionally share one response.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Content not found",
        ) from exc

    return ContentEventLookupResponse(content_id=content_id, event=event)


@router.get("/{content_id}/event/coverage", response_model=ContentEventCoverageLookupResponse)
async def get_content_event_coverage(
    content_id: int,
    member_limit: int = Query(20, ge=1, le=20),
    member_offset: int = Query(0, ge=0),
    expected_event_id: int | None = Query(None, ge=1),
    expected_version: int | None = Query(None, ge=1),
    current_user: Any | None = Depends(get_optional_current_user),
    db: AsyncSession = Depends(get_db),
) -> ContentEventCoverageLookupResponse:
    """Other accepted reports, paginated relative to this displayed report."""
    try:
        event = await get_event_coverage(
            db,
            content_id,
            visible_user_id=current_user.id if current_user is not None else None,
            member_limit=member_limit,
            member_offset=member_offset,
            expected_event_id=expected_event_id,
            expected_version=expected_version,
        )
    except ContentEventNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Content not found") from exc
    except ContentEventConflictError as exc:
        raise HTTPException(status_code=409, detail="Event changed; reload coverage") from exc
    return ContentEventCoverageLookupResponse(content_id=content_id, event=event)
