"""
Weekly Digest API endpoints.
"""

from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.daily_report_repo import DailyReportRepository
from app.repositories.pick_mark_repo import PickMarkRepository
from app.repositories.weekly_digest_repo import WeeklyDigestRepository
from app.schemas.weekly_digest import (
    WeeklyDigestListResponse,
    WeeklyDigestResponse,
    WeeklyDigestWeeksResponse,
)
from app.services.weekly_digest import generate_weekly_digest

router = APIRouter(prefix="/weekly-digests", tags=["weekly-digests"], dependencies=[Depends(get_current_user)])


@router.get("/current", response_model=WeeklyDigestResponse)
async def get_current_week_digest(db: AsyncSession = Depends(get_db)):
    """Get or generate the current week's digest."""
    digest = await generate_weekly_digest(db)
    return digest


@router.get("/by-week", response_model=WeeklyDigestResponse)
async def get_digest_by_week(
    week_key: str = Query(..., description="Week key in YYYY-WNN format, e.g. 2025-W21"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch a single digest by its week key."""
    repo = WeeklyDigestRepository(db)
    digest = await repo.get_by_week_key(week_key)
    if digest is None:
        raise HTTPException(status_code=404, detail=f"No digest found for {week_key}")
    return digest


@router.get("/weeks", response_model=WeeklyDigestWeeksResponse)
async def list_digest_weeks(db: AsyncSession = Depends(get_db)):
    """List all weeks that have digests, newest first."""
    repo = WeeklyDigestRepository(db)
    weeks = await repo.get_weeks_with_digests()
    return {"weeks": weeks}


@router.get("", response_model=WeeklyDigestListResponse)
async def list_digests(
    limit: int = 8,
    db: AsyncSession = Depends(get_db),
):
    """List recent weekly digests."""
    repo = WeeklyDigestRepository(db)
    total = await repo.count_all()
    items = await repo.get_latest(limit)

    return {"items": items, "total": total}


@router.post("/generate", response_model=WeeklyDigestResponse)
async def trigger_generate(
    week_key: str | None = Query(None, description="Week key to generate (defaults to current week)"),
    db: AsyncSession = Depends(get_db),
):
    """Force regenerate a weekly digest for the given week (or current week)."""
    # Parse week_key to a reference date for generation
    reference_date = None
    if week_key:
        # Parse "2025-W21" format: find the Monday of that week
        try:
            parts = week_key.split("-W")
            year = int(parts[0])
            week_num = int(parts[1])
            # ISO week date: Monday of the given ISO week
            reference_date = date.fromisocalendar(year, week_num, 1)
        except (ValueError, IndexError):
            raise HTTPException(
                status_code=400, detail=f"Invalid week_key format: {week_key}. Use YYYY-WNN format, e.g. 2025-W21"
            ) from None

    # Delete existing digest to force regeneration
    if reference_date:
        from app.services.weekly_digest import _get_week_range

        wk, _, _, _ = _get_week_range(reference_date)
    else:
        from app.services.weekly_digest import _get_week_range

        wk, _, _, _ = _get_week_range()

    repo = WeeklyDigestRepository(db)
    existing_digest = await repo.get_by_week_key(wk)
    if existing_digest:
        existing_digest.status = "PENDING"
        await db.flush()

    digest = await generate_weekly_digest(db, reference_date=reference_date)
    return digest


@router.get("/pick-tracking")
async def get_pick_tracking(
    week_key: str = Query(..., description="Week key YYYY-WNN"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """追踪用户在指定周的日报中标记的选题。

    返回每个被标记的选题：
    - 标记类型（write/watch/skip）
    - 标记日期
    - 该选题在本周出现在几天日报的 top_picks 里（连续在榜天数）

    这是周报「金字塔压缩」的独特价值——日报看不到跨日趋势，
    周报能看到选题的持续性和变化。
    """
    import json as _json

    # 解析 week_key 得到日期范围
    try:
        parts = week_key.split("-W")
        year = int(parts[0])
        week_num = int(parts[1])
        monday = date.fromisocalendar(year, week_num, 1)
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail=f"Invalid week_key: {week_key}") from None
    sunday = monday + timedelta(days=6)

    # 1. 查用户本周的所有标记
    pick_repo = PickMarkRepository(db)
    marks = await pick_repo.list_by_user_date_range(user.id, monday, sunday)
    if not marks:
        return {
            "marks": [],
            "total": 0,
            "week_key": week_key,
            "week_range": f"{monday.isoformat()} ~ {sunday.isoformat()}",
        }

    # 2. 查本周所有日报的 top_picks（统计每个标记选题出现在几天的榜单里）
    report_repo = DailyReportRepository(db)
    reports = await report_repo.list_done_by_date_range(monday.isoformat(), sunday.isoformat())

    # 构建 标题 → 出现日期集合
    title_to_dates: dict[str, list[str]] = {}
    for report in reports:
        try:
            picks = _json.loads(report.top_picks or "[]")
            for pick in picks:
                title = pick.get("title", "").strip()
                if title:
                    title_to_dates.setdefault(title, []).append(report.report_date)
        except (_json.JSONDecodeError, TypeError):
            continue

    # 3. 组装结果
    result_marks = []
    for mark in marks:
        title = mark.pick_title.strip()
        appearances = title_to_dates.get(title, [])

        # 模糊匹配（标记标题可能是日报 pick 标题的子串）
        if not appearances:
            for rpt_title, dates in title_to_dates.items():
                if title in rpt_title or rpt_title in title:
                    appearances = dates
                    break

        result_marks.append(
            {
                "pick_title": mark.pick_title,
                "action": mark.action,
                "mark_date": str(mark.report_date),
                "pick_category": mark.pick_category,
                "appearances_in_week": len(appearances),
                "appearance_dates": appearances,
                "pick_source_url": mark.pick_source_url,
            }
        )

    # 按 appearances 降序排（最持续的排前面）
    result_marks.sort(key=lambda x: x["appearances_in_week"], reverse=True)

    return {
        "marks": result_marks,
        "total": len(result_marks),
        "week_key": week_key,
        "week_range": f"{monday.isoformat()} ~ {sunday.isoformat()}",
    }
