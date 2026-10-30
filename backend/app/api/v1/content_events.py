"""Public read API for canonical content events."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user, get_optional_current_user
from app.core.database import get_db
from app.schemas.content_event import (
    ContentEventCoverageLookupResponse,
    ContentEventLookupResponse,
    EventAngleAnalysisResponse,
)
from app.services.content_event_angles import EventAngleAnalysisError, analyze_event_angles
from app.services.content_event_coverage import get_event_coverage
from app.services.content_event_service import (
    ContentEventConflictError,
    ContentEventNotFoundError,
    ContentEventService,
)
from app.services.llm.budget_guard import LlmBudgetExceededError
from app.services.llm.circuit_breaker import CircuitOpenError
from app.services.llm.provider import LlmCapacityUnavailableError, LlmContextWindowExceededError

logger = logging.getLogger(__name__)

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


@router.post("/{content_id}/event/angles", response_model=EventAngleAnalysisResponse)
async def analyze_content_event_angles(
    content_id: int,
    current_user: Any = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> EventAngleAnalysisResponse:
    """Analyze angle scarcity across the visible event's accepted reports.

    Read-only: no business table writes; the LLM call itself is traced by the
    existing call_trace infrastructure.
    """

    try:
        result = await analyze_event_angles(db, content_id, visible_user_id=current_user.id)
    except ContentEventNotFoundError as exc:
        # Missing and non-visible content intentionally share one response.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content not found") from exc
    except EventAngleAnalysisError as exc:
        logger.warning("Event angle analysis unparsable for content %s", content_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="事件角度分析失败：模型返回结构不可用，请稍后重试",
        ) from exc
    except (
        CircuitOpenError,
        LlmCapacityUnavailableError,
        LlmBudgetExceededError,
        LlmContextWindowExceededError,
    ) as exc:
        # LLM 链路失败 → 502 显式文案；不折叠成 200 假成功（AGENTS 2.1）。
        details = {
            CircuitOpenError: "事件角度分析失败：模型链路熔断中，请稍后重试",
            LlmCapacityUnavailableError: "事件角度分析失败：模型服务暂不可用，请稍后重试",
            LlmBudgetExceededError: "事件角度分析失败：模型预算已耗尽，请稍后重试",
            LlmContextWindowExceededError: "事件角度分析失败：事件内容超出模型上下文，请稍后重试",
        }
        detail = next(
            (text for exc_type, text in details.items() if isinstance(exc, exc_type)), "事件角度分析失败，请稍后重试"
        )
        logger.warning("Event angle analysis LLM failure for content %s: %s", content_id, type(exc).__name__)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail) from exc
    except Exception as exc:
        logger.warning("Event angle analysis failed for content %s", content_id, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="事件角度分析失败，请稍后重试",
        ) from exc
    return EventAngleAnalysisResponse.model_validate(result)
