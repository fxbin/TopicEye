"""
Webnovel report API endpoints.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webnovel/reports", tags=["webnovel-reports"])


@router.get("/weekly")
async def weekly_report(
    days: int = Query(7, ge=3, le=31),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return weekly webnovel ranking history and movement analysis.

    优先走 DuckDB 分析层（列式存储 + 窗口函数加速），
    不可用时 fallback 到 OLTP 路径。结果缓存 5 分钟。
    """
    import json

    from app.services.json_cache import get_cached_json, set_cached_json

    cache_key = f"webnovel_weekly:{days}"
    cached = get_cached_json(cache_key, ttl_seconds=300)  # 5 min TTL
    if cached:
        return Response(
            content=cached[0],
            media_type="application/json",
            headers={"X-Webnovel-Weekly-Cache": f"HIT; age={cached[1]:.1f}s"},
        )

    # ── 优先 DuckDB ──
    result = None
    backend = "oltp"
    try:
        from app.services.duckdb_service import get_analytics

        analytics = get_analytics()
        if analytics.available:
            result = analytics.query_webnovel_weekly(days=days)
            # 如果 DuckDB 返回的数据为空（SQL 错误被静默捕获），回退到 OLTP
            if not result or result.get("summary", {}).get("total_items", 0) == 0:
                logger.info("Webnovel weekly DuckDB returned empty, falling back to OLTP")
                result = None
            else:
                backend = "duckdb"
    except Exception as exc:
        logger.debug("Webnovel weekly DuckDB path failed, falling back: %s", exc)

    # ── OLTP fallback ──
    if result is None:
        from app.services.webnovel_report import build_weekly_webnovel_report

        result = await build_weekly_webnovel_report(db, days=days)
        backend = "oltp"

    payload = json.dumps(result, default=str, ensure_ascii=False)
    # 只缓存有实际数据的结果
    if result.get("summary", {}).get("total_items", 0) > 0:
        set_cached_json(cache_key, payload)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"X-Webnovel-Weekly-Cache": "MISS", "X-Analytics-Backend": backend},
    )
