"""前端体验指标上报与聚合（#179）。

- POST /metrics/web-vitals          浏览器上报（登录可选，非法条目逐条丢弃）
- GET  /metrics/web-vitals/summary  窗口内 p75 聚合（管理员）

上报端点不要求管理员：``/metrics`` 那个 router 整体带管理员依赖，
若把接收端点挂进去会导致未登录用户完全无法上报——而登录页恰恰是
体验最差、也最该被观测的页面。

上报失败一律不影响客户端：这是遥测通道，不是业务链路。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_optional_current_user
from app.core.database import get_db
from app.models.user import User
from app.schemas.web_vitals import (
    WebVitalReportRequest,
    WebVitalReportResponse,
    WebVitalsSummaryResponse,
)
from app.services import web_vitals_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/metrics/web-vitals", tags=["web-vitals"])


@router.post("", response_model=WebVitalReportResponse, status_code=202)
async def report_web_vitals(
    req: WebVitalReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    """接收一批前端体验指标样本。

    返回落库条数与被丢弃条数；非法条目逐条丢弃，不整批失败。
    """
    samples = [
        (sample.metric, sample.value, sample.path, sample.navigation_type, sample.device_class)
        for sample in req.samples
    ]
    user_id = current_user.id if current_user else None
    try:
        accepted, rejected = await web_vitals_service.record_samples(db, samples, user_id=user_id)
    except Exception:
        # 遥测通道不该把错误抛回浏览器；真实原因留在日志里。
        # 先回滚：失败的事务若带坏状态，后续 get_db 的 commit 会连带 500。
        await db.rollback()
        logger.warning("web vitals report failed: %d samples dropped", len(samples), exc_info=True)
        return WebVitalReportResponse(accepted=0, rejected=len(samples))
    if rejected:
        logger.info("web vitals report: accepted=%d rejected=%d", accepted, rejected)
    return WebVitalReportResponse(accepted=accepted, rejected=rejected)


@router.get("/summary", response_model=WebVitalsSummaryResponse)
async def web_vitals_summary(
    hours: int = Query(24, ge=1, le=720, description="回看窗口（小时），最大 30 天"),
    navigation_type: str = Query(
        "navigate",
        description="navigate=首次加载（经典 LCP 口径）| soft-navigation | all",
    ),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """窗口内各指标的 p50/p75/p95 与按路由的 p75 拆解。"""
    normalized_navigation = navigation_type if navigation_type in {"navigate", "soft-navigation", "all"} else "navigate"
    summary = await web_vitals_service.summarize(db, hours=hours, navigation_type=normalized_navigation)
    return WebVitalsSummaryResponse(**summary)
