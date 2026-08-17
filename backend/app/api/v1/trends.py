"""
Trend tracking API endpoints.

Endpoints:
- POST /api/v1/trends/snapshot  — trigger daily snapshot
- GET  /api/v1/trends/topics    — topic trend curves (last N days)
- GET  /api/v1/trends/keywords  — keyword word cloud (last N days)

Read queries use DuckDB as the fixed analytical layer.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import async_session, get_db
from app.schemas.trend import TrendEvidenceResponse
from app.services import duckdb_service
from app.services.trends import (
    get_keyword_trend_evidence,
    get_topic_trend_evidence,
    snapshot_daily_trends,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trends", tags=["trends"])
ANALYTICS_HEADERS = {"X-Analytics-Backend": "duckdb"}


@router.post("/snapshot", dependencies=[Depends(get_current_admin_user)])
async def trigger_snapshot(
    target_date: str | None = Query(None, description="YYYY-MM-DD, defaults to today"),
):
    """Manually trigger a trend snapshot for a given date."""
    td = date.fromisoformat(target_date) if target_date else None
    async with async_session() as db:
        result = await snapshot_daily_trends(db, td)
        await db.commit()
    return {"status": "ok", **result}


@router.get("/topics")
async def topic_trends(
    response: Response,
    days: int = Query(7, ge=1, le=30, description="Number of days to look back"),
):
    """Get topic trend data for charts through DuckDB."""
    try:
        trends = await duckdb_service.run_query(lambda: duckdb_service.query_trend_topics(days=days))
    except Exception as exc:
        logger.exception("DuckDB topic trend query failed")
        raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc
    response.headers.update(ANALYTICS_HEADERS)
    return {"days": days, "trends": trends}


@router.get("/keywords")
async def keyword_cloud(
    response: Response,
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50, ge=10, le=200),
):
    """Get keyword frequency for word cloud visualization through DuckDB."""
    try:
        keywords = await duckdb_service.run_query(lambda: duckdb_service.query_keyword_cloud(days=days, limit=limit))
    except Exception as exc:
        logger.exception("DuckDB keyword cloud query failed")
        raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc
    response.headers.update(ANALYTICS_HEADERS)
    return {"days": days, "keywords": keywords}


@router.get("/topics/{topic_id}/evidence", response_model=TrendEvidenceResponse)
async def topic_trend_evidence(
    topic_id: int,
    snapshot_date: date = Query(..., alias="date", description="Snapshot date (YYYY-MM-DD)"),
    evidence_filter: Literal["all", "selected", "evidenced"] = Query("all", alias="filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> TrendEvidenceResponse:
    """Drill through one public topic trend point to its frozen member set."""
    payload = await get_topic_trend_evidence(
        db,
        topic_id=topic_id,
        snapshot_date=snapshot_date,
        evidence_filter=evidence_filter,
        page=page,
        page_size=page_size,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Trend snapshot not found")
    return TrendEvidenceResponse(**payload)


@router.get("/keywords/evidence", response_model=TrendEvidenceResponse)
async def keyword_trend_evidence(
    keyword: str = Query(..., min_length=1, max_length=200),
    days: int = Query(7, ge=1, le=30),
    evidence_filter: Literal["all", "selected", "evidenced"] = Query("all", alias="filter"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> TrendEvidenceResponse:
    """Drill through a public keyword's frozen members across a date interval."""
    payload = await get_keyword_trend_evidence(
        db,
        keyword=keyword,
        days=days,
        evidence_filter=evidence_filter,
        page=page,
        page_size=page_size,
    )
    if payload is None:
        raise HTTPException(status_code=404, detail="Trend keyword snapshots not found")
    return TrendEvidenceResponse(**payload)
