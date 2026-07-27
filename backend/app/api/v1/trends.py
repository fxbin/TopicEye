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

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.v1.auth import get_current_admin_user
from app.core.database import async_session
from app.services import duckdb_service
from app.services.trends import snapshot_daily_trends

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
        trends = duckdb_service.query_trend_topics(days=days)
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
        keywords = duckdb_service.query_keyword_cloud(days=days, limit=limit)
    except Exception as exc:
        logger.exception("DuckDB keyword cloud query failed")
        raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc
    response.headers.update(ANALYTICS_HEADERS)
    return {"days": days, "keywords": keywords}
