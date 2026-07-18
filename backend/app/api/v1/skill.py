"""Skill read-API — let external agents read TopicEye curated data.

Exposes three read-only endpoints so external agents (ZCode / Claude skills,
n8n, custom scripts) can fetch TopicEye's curated output without re-running
the scoring pipeline themselves:

  GET /api/v1/skill/today-picks  — 今日精选选题（含评分明细）
  GET /api/v1/skill/daily-report — 最新日报（overview / top_picks / keywords）
  GET /api/v1/skill/trends       — 话题趋势 + 关键词词频（合并）

Auth uses ``Depends(get_current_user)`` which accepts both browser session
tokens and personal API tokens (create one at ``POST /api/v1/me/api-tokens``).
All endpoints are thin wrappers around existing service functions — no business
logic is duplicated.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.daily_report_repo import DailyReportRepository
from app.schemas.daily_report import DailyReportResponse
from app.schemas.skill import SkillTodayPicksResponse, SkillTrendsResponse
from app.services import duckdb_service
from app.services.daily_report import get_latest_today_report
from app.services.today_picks import build_today_picks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/skill", tags=["skill"], dependencies=[Depends(get_current_user)])


@router.get(
    "/today-picks",
    response_model=SkillTodayPicksResponse,
    summary="今日精选选题（agent 读取）",
    description=(
        "返回最近 N 小时内 TopicEye 的精选选题，含每条的评分明细 "
        "（analysis.adjusted_curation_score / score_breakdown）。外部 agent "
        '可用它回答"今天有什么值得写的选题"。返回结构与 /contents/today-picks 一致。'
        "\n\nExample: `GET /api/v1/skill/today-picks?hours=48&limit=20`"
    ),
)
async def skill_today_picks(
    db: AsyncSession = Depends(get_db),
    category: str | None = Query(None, description="按分类过滤，如 AI / 产品"),
    hours: int = Query(48, ge=1, le=168, description="回看时间窗（小时）"),
    limit: int = Query(20, ge=1, le=100, description="返回条数上限"),
    current_user: User = Depends(get_current_user),
) -> SkillTodayPicksResponse:
    payload = await build_today_picks(db, category=category, hours=hours, limit=limit)
    return SkillTodayPicksResponse(**payload)


@router.get(
    "/daily-report",
    response_model=DailyReportResponse,
    summary="日报（agent 读取）",
    description=(
        "返回指定日期的日报；缺省 date 时返回今天的最新日报（无则自动生成快照）。"
        "日报含 overview（选题综述）、top_picks（精选条目）、keywords、trends 等字段。"
        "外部 agent 可用它获取已编辑的选题综述。"
        "\n\nExample: `GET /api/v1/skill/daily-report?date=2026-07-15`"
    ),
)
async def skill_daily_report(
    db: AsyncSession = Depends(get_db),
    date: str | None = Query(None, description="YYYY-MM-DD，缺省=今天"),
    current_user: User = Depends(get_current_user),
) -> DailyReportResponse:
    if date:
        report = await DailyReportRepository(db).get_by_date(date, owner_user_id=current_user.id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No report found for {date}")
        return report
    report = await get_latest_today_report(db, owner_user_id=current_user.id)
    return report


@router.get(
    "/trends",
    response_model=SkillTrendsResponse,
    summary="话题趋势 + 关键词（agent 读取）",
    description=(
        "合并返回话题趋势（topics）和关键词词频（keywords），减少 agent 往返。"
        "数据来自 DuckDB 分析层，读取的是每日快照（topic_trends）。"
        "DuckDB 不可用时返回 503。"
        "\n\nExample: `GET /api/v1/skill/trends?days=7&limit=50`"
    ),
)
async def skill_trends(
    response: Response,
    days: int = Query(7, ge=1, le=30, description="回看天数"),
    limit: int = Query(50, ge=10, le=200, description="关键词返回上限"),
    current_user: User = Depends(get_current_user),
) -> SkillTrendsResponse:
    try:
        topics = duckdb_service.query_trend_topics(days=days)
        keywords = duckdb_service.query_keyword_cloud(days=days, limit=limit)
    except Exception as exc:
        logger.exception("skill trends DuckDB query failed")
        raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc
    response.headers["X-Analytics-Backend"] = "duckdb"
    return SkillTrendsResponse(days=days, topics=topics, keywords=keywords)
