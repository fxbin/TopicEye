"""
Daily Report API endpoints.
"""

from __future__ import annotations

import logging
from typing import Tuple, Optional

from datetime import date as date_cls, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db, async_session
from app.models.content import ContentItem
from app.models.daily_report import DailyReport
from app.models.user import User
from app.repositories.daily_report_repo import DailyReportRepository
from app.schemas.daily_report import (
    DailyReportResponse,
    DailyReportListResponse,
    DailyReportDatesResponse,
    DailyReportCalendarResponse,
)
from app.services.daily_report import LOCAL_TZ, WEEKDAYS, generate_daily_report, get_latest_today_report
from app.services.plan_catalog import plan_allows_private_source

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/daily-reports", tags=["daily-reports"], dependencies=[Depends(get_current_user)])


# ── /me series: user-owned private daily reports (T2) ───────────────────
# Declared BEFORE /today so FastAPI matches the literal "me" segment first.


@router.get("/me/today", response_model=DailyReportResponse)
async def get_my_today_report(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get today's user-owned daily report, generating one if none exists.

    Requires ``plan_allows_private_source`` (Pro and above). T1-3a shares
    the same paywall.
    """
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    return await get_latest_today_report(db, owner_user_id=current_user.id)


@router.get("/me/by-date", response_model=DailyReportResponse)
async def get_my_report_by_date(
    date: str = Query(..., description="Report date in YYYY-MM-DD format"),
    edition: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Fetch the user's own report for a date, or latest snapshot if final does not exist."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    repo = DailyReportRepository(db)
    report = await repo.get_by_date(date, edition=edition, owner_user_id=current_user.id)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No my-report found for {date}")
    return report


@router.get("/me/dates", response_model=DailyReportDatesResponse)
async def list_my_report_dates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all dates that have the user's own reports, newest first."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    repo = DailyReportRepository(db)
    dates = await repo.get_dates_with_reports(owner_user_id=current_user.id)
    return {"dates": dates}


@router.post("/me/generate", response_model=DailyReportResponse)
async def trigger_my_generate(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force generate today's user-owned daily report snapshot."""
    if not plan_allows_private_source(current_user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    return await generate_daily_report(db, force=True, owner_user_id=current_user.id)


@router.get("/today", response_model=DailyReportResponse)
async def get_today_report(db: AsyncSession = Depends(get_db)):
    """Get today's latest daily report snapshot, generating one if none exists."""
    report = await get_latest_today_report(db)
    return report


@router.get("/by-date", response_model=DailyReportResponse)
async def get_report_by_date(
    date: str = Query(..., description="Report date in YYYY-MM-DD format"),
    edition: str | None = Query(None, description="Optional edition: snapshot/noon/evening/final/manual"),
    db: AsyncSession = Depends(get_db),
):
    """Fetch final report for a date, or latest snapshot if final does not exist."""
    repo = DailyReportRepository(db)
    report = await repo.get_by_date(date, edition=edition)
    if report is None:
        raise HTTPException(status_code=404, detail=f"No report found for {date}")
    return report


@router.get("/dates", response_model=DailyReportDatesResponse)
async def list_report_dates(db: AsyncSession = Depends(get_db)):
    """List all dates that have reports, newest first."""
    repo = DailyReportRepository(db)
    dates = await repo.get_dates_with_reports()
    return {"dates": dates}


@router.get("/calendar", response_model=DailyReportCalendarResponse)
async def get_report_calendar(
    days: int = Query(30, ge=7, le=90, description="Number of recent days to include"),
    db: AsyncSession = Depends(get_db),
):
    """Return a recent date map for spotting missing or failed daily reports."""
    today = datetime.now(LOCAL_TZ).date()
    start = today - timedelta(days=days - 1)
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.report_date >= start.isoformat())
        .where(DailyReport.report_date <= today.isoformat())
        .order_by(DailyReport.report_date.desc(), DailyReport.cutoff_at.desc(), DailyReport.updated_at.desc())
    )
    reports = result.scalars().all()

    grouped: dict[str, list[DailyReport]] = {}
    for report in reports:
        grouped.setdefault(report.report_date, []).append(report)

    calendar_statuses = {"DONE", "ERROR", "GENERATING", "MISSING"}

    def pick_calendar_report(items: list[DailyReport], current_date: date_cls) -> tuple[DailyReport | None, str]:
        if not items:
            return None, "MISSING"

        if current_date < today:
            final_reports = [item for item in items if item.edition == "final"]
            if not final_reports:
                return items[0], "MISSING"
            selected = final_reports[0]
            return selected, selected.status if selected.status in calendar_statuses else "MISSING"

        done = [item for item in items if item.status == "DONE"]
        if done:
            return done[0], "DONE"
        selected = items[0]
        return selected, selected.status if selected.status in calendar_statuses else "MISSING"

    out = []
    counts = {"DONE": 0, "ERROR": 0, "GENERATING": 0, "MISSING": 0}
    for offset in range(days):
        current = today - timedelta(days=offset)
        key = current.isoformat()
        selected, status = pick_calendar_report(grouped.get(key, []), current)
        if status not in counts:
            status = "MISSING"
        counts[status] += 1
        out.append(
            {
                "report_date": key,
                "weekday": WEEKDAYS[current.weekday()],
                "status": status,
                "edition": selected.edition if selected else None,
                "generated_at": selected.generated_at if selected else None,
                "cutoff_at": selected.cutoff_at if selected else None,
                "takeaway": selected.takeaway[:80] if selected and selected.takeaway else None,
                "content_count": selected.content_count if selected else 0,
                "analyzed_count": selected.analyzed_count if selected else 0,
                "topic_count": selected.topic_count if selected else 0,
                "has_report": selected is not None and status != "MISSING",
                "can_generate": status in {"MISSING", "ERROR", "DONE"},
                "is_today": current == today,
            }
        )

    return {
        "days": out,
        "total_days": days,
        "done_count": counts["DONE"],
        "error_count": counts["ERROR"],
        "missing_count": counts["MISSING"],
        "generating_count": counts["GENERATING"],
    }


@router.get("", response_model=DailyReportListResponse)
async def list_reports(
    limit: int = 7,
    db: AsyncSession = Depends(get_db),
):
    """List recent daily reports."""
    count_result = await db.execute(select(func.count()).select_from(DailyReport))
    total = count_result.scalar() or 0

    result = await db.execute(
        select(DailyReport).order_by(DailyReport.report_date.desc(), DailyReport.cutoff_at.desc()).limit(limit)
    )
    items = result.scalars().all()

    return {"items": items, "total": total}


@router.post("/generate", response_model=DailyReportResponse)
async def trigger_generate(db: AsyncSession = Depends(get_db)):
    """Force generate a daily report snapshot for a date/window."""
    report = await generate_daily_report(db, force=True)
    return report


@router.post("/generate-version")
async def trigger_generate_version(
    target_date: str | None = Query(None, description="Target date in YYYY-MM-DD, defaults to today"),
    edition: str | None = Query(None, description="snapshot/noon/evening/final/manual"),
    cutoff_at: str | None = Query(None, description="ISO datetime cutoff, defaults to now"),
    force: bool = Query(True, description="Regenerate even if this exact version exists"),
    db: AsyncSession = Depends(get_db),
):
    """Generate a specific daily report version/window (async).

    日报生成调 LLM 耗时 30-60 秒，超过 Next.js 代理默认超时。
    改为异步：先创建/标记 GENERATING 记录立即返回 202，
    后台 task 完成后前端通过轮询 /today 拿最终结果。
    """
    import asyncio
    from app.services.daily_report import _local_today, _day_window, _local_window_to_utc_naive

    parsed_date = date_cls.fromisoformat(target_date) if target_date else _local_today()
    parsed_cutoff = datetime.fromisoformat(cutoff_at) if cutoff_at else None
    normalized_edition = edition or "manual"

    # 快速创建 GENERATING 占位记录（如果还没有）
    from app.services.daily_report import VALID_EDITIONS
    if normalized_edition not in VALID_EDITIONS:
        normalized_edition = "manual"

    window_start, window_end = _day_window(parsed_date, parsed_cutoff, normalized_edition)
    utc_start, utc_end = _local_window_to_utc_naive(window_start, window_end)

    # 查是否已有记录（取最新一条，避免历史脏数据导致 MultipleResultsFound）
    existing = await db.execute(
        select(DailyReport)
        .where(
            DailyReport.report_date == parsed_date.isoformat(),
            DailyReport.edition == normalized_edition,
            DailyReport.owner_user_id.is_(None),
        )
        .order_by(DailyReport.id.desc())
        .limit(1)
    )
    report = existing.scalar_one_or_none()

    if report and report.status == "DONE" and not force:
        return report

    if report:
        report.status = "GENERATING"
        report.updated_at = datetime.now(LOCAL_TZ)
    else:
        report = DailyReport(
            report_date=parsed_date.isoformat(),
            weekday=WEEKDAYS[parsed_date.weekday()],
            edition=normalized_edition,
            window_start=utc_start,
            window_end=utc_end,
            cutoff_at=parsed_cutoff,
            status="GENERATING",
            overview="正在生成日报...",
        )
        db.add(report)

    await db.commit()
    report_id = report.id
    report_date_iso = parsed_date.isoformat()

    # 后台异步生成（独立 DB session，不阻塞当前请求）
    async def _bg_generate():
        async with async_session() as bg_db:
            try:
                await generate_daily_report(
                    bg_db,
                    target_date=parsed_date,
                    edition=normalized_edition,
                    cutoff_at=parsed_cutoff,
                    force=True,
                )
            except Exception as e:
                logger.error("Background daily report generation failed: %s", e)
                # 标记失败
                try:
                    fail_result = await bg_db.execute(
                        select(DailyReport).where(DailyReport.id == report_id)
                    )
                    fail_report = fail_result.scalar_one_or_none()
                    if fail_report:
                        fail_report.status = "ERROR"
                        fail_report.overview = f"生成失败: {str(e)[:200]}"
                        await bg_db.commit()
                except Exception:
                    pass

    asyncio.create_task(_bg_generate())

    # 返回 GENERATING 状态（HTTP 202 Accepted）
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=202,
        content={
            "id": report_id,
            "report_date": report_date_iso,
            "status": "GENERATING",
            "message": "日报正在后台生成，请稍后刷新查看",
        },
    )


def _extract_sparkline_keywords(title: str, limit: int = 4) -> list[str]:
    """从选题标题里提取 1-4 个最具区分度的关键词供 sparkline 查询。

    - 中文走 jieba 切词，英文/数字按 regex 切
    - 去除常见停用词 + 单字无意义词
    - 按长度排序优先长词（专有名词通常更长），去重后取前 N 个
    """
    import re as _re
    if not title:
        return []
    stopwords = {"的", "了", "在", "是", "和", "与", "或", "为", "我", "你", "他", "她", "它", "也", "都", "就", "把", "被", "了", "着",
                 "the", "a", "an", "of", "to", "in", "on", "at", "by", "for", "with"}
    # 中文用 jieba 切词
    try:
        import jieba
        chinese_words = [w for w in jieba.lcut_for_search(title) if len(w) >= 2 and w not in stopwords]
    except Exception:
        # fallback: regex 粗切
        chinese_words = [w for w in _re.findall(r"[\u4e00-\u9fa5]{2,}", title) if w not in stopwords]
    # 英文/数字 token
    en_tokens = [w for w in _re.findall(r"[A-Za-z0-9]+", title) if len(w) >= 2 and w.lower() not in stopwords]
    tokens = chinese_words + en_tokens
    tokens.sort(key=lambda t: (-len(t), t))
    seen, result = set(), []
    for t in tokens:
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(t)
        if len(result) >= limit:
            break
    return result


@router.get("/sparkline")
async def get_sparkline(
    title: str = Query(..., min_length=2, max_length=200, description="选题标题"),
    hours: int = Query(48, ge=4, le=168, description="时间窗口小时数"),
    bucket_hours: int = Query(2, ge=1, le=12, description="分桶大小"),
    db: AsyncSession = Depends(get_db),
):
    """返回选题近 N 小时的内容流入速率（按指定小时分桶），给前端画 sparkline。

    用 ILIKE 任意一个关键词命中即算（OR 匹配），保证标题里 1-2 个核心词也能查到曲线。
    """
    from sqlalchemy import or_

    keywords = _extract_sparkline_keywords(title)
    if not keywords:
        return {"points": [], "keywords": [], "total": 0, "window_hours": hours}

    cutoff = datetime.now() - timedelta(hours=hours)
    # ILIKE 任一关键词，OR 组合；过滤掉 AI 分析失败的（duplicate_of）、当天以外未分类的噪声
    pattern_clauses = [
        ContentItem.title.ilike(f"%{kw}%") for kw in keywords
    ]
    rows = await db.execute(
        select(
            func.date_trunc("hour", ContentItem.crawled_at).label("ts"),
            func.count().label("cnt"),
        )
        .where(
            ContentItem.crawled_at >= cutoff,
            ContentItem.status == "analyzed",
            ContentItem.duplicate_of.is_(None),
            or_(*pattern_clauses),
        )
        .group_by("ts")
    )
    raw = rows.all()  # [(datetime_hour, count), ...]

    # 桶化：按 bucket_hours 聚合
    bucket_seconds = bucket_hours * 3600
    bucket_counts: dict[int, int] = {}
    for ts, cnt in raw:
        bucket_key = int(ts.timestamp() // bucket_seconds)
        bucket_counts[bucket_key] = bucket_counts.get(bucket_key, 0) + int(cnt)

    if not bucket_counts:
        return {"points": [], "keywords": keywords, "total": 0, "window_hours": hours}

    # 生成连续桶时间序列
    sorted_buckets = sorted(bucket_counts.keys())
    min_bucket = sorted_buckets[0]
    max_bucket = sorted_buckets[-1]
    # 对齐到当前时刻
    now_bucket = int(datetime.now().timestamp() // bucket_seconds)
    points: list[dict] = []
    for b in range(min_bucket, now_bucket + 1):
        ts_dt = datetime.fromtimestamp(b * bucket_seconds)
        points.append({
            "ts": ts_dt.isoformat(),
            "count": bucket_counts.get(b, 0),
        })

    # 相对变化率基线（避免不同选题绝对值差异过大）：用平均值作 baseline
    counts = [p["count"] for p in points]
    baseline = max(1.0, sum(counts) / max(1, len(counts)))
    for p in points:
        p["baseline"] = round(baseline, 2)

    return {
        "points": points,
        "keywords": keywords,
        "total": sum(counts),
        "window_hours": hours,
    }


# ── 选题标记（写这个/观察/跳过）──────────────────────────────


@router.get("/pick-marks")
async def list_pick_marks(
    report_date: str = Query(None, description="按日期过滤（YYYY-MM-DD）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取用户的选题标记列表。"""
    from app.models.pick_mark import PickMark
    from datetime import date as date_type

    parsed_date = date_type.fromisoformat(report_date) if report_date else None
    stmt = select(PickMark).where(PickMark.user_id == user.id)
    if parsed_date:
        stmt = stmt.where(PickMark.report_date == parsed_date)
    stmt = stmt.order_by(PickMark.updated_at.desc())
    result = await db.execute(stmt)
    marks = result.scalars().all()
    return {
        "marks": [
            {
                "report_date": str(m.report_date),
                "pick_title": m.pick_title,
                "action": m.action,
                "pick_category": m.pick_category,
                "pick_source_url": m.pick_source_url,
            }
            for m in marks
        ],
        "total": len(marks),
    }


@router.post("/pick-marks")
async def upsert_pick_mark(
    body: dict,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """创建或更新选题标记（同一 user+date+title 只保留一条，覆盖 action）。"""
    from app.models.pick_mark import PickMark
    from datetime import date as date_type

    report_date_str = body.get("report_date")
    pick_title = body.get("pick_title")
    action = body.get("action")

    if not report_date_str or not pick_title or not action:
        raise HTTPException(status_code=400, detail="report_date, pick_title, action are required")
    if action not in ("write", "watch", "skip"):
        raise HTTPException(status_code=400, detail="action must be write/watch/skip")

    parsed_date = date_type.fromisoformat(report_date_str)
    pick_category = body.get("pick_category")
    pick_source_url = body.get("pick_source_url")

    # Upsert：先查有没有
    existing = await db.execute(
        select(PickMark).where(
            PickMark.user_id == user.id,
            PickMark.report_date == parsed_date,
            PickMark.pick_title == pick_title,
        )
    )
    mark = existing.scalar_one_or_none()
    if mark:
        mark.action = action
        mark.pick_category = pick_category or mark.pick_category
        mark.pick_source_url = pick_source_url or mark.pick_source_url
    else:
        mark = PickMark(
            user_id=user.id,
            report_date=parsed_date,
            pick_title=pick_title,
            action=action,
            pick_category=pick_category,
            pick_source_url=pick_source_url,
        )
        db.add(mark)
    await db.commit()
    return {"status": "ok", "action": action}


@router.delete("/pick-marks")
async def delete_pick_mark(
    report_date: str = Query(...),
    pick_title: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除选题标记。"""
    from app.models.pick_mark import PickMark
    from sqlalchemy import delete as sa_delete
    from datetime import date as date_type

    parsed_date = date_type.fromisoformat(report_date)
    await db.execute(
        sa_delete(PickMark).where(
            PickMark.user_id == user.id,
            PickMark.report_date == parsed_date,
            PickMark.pick_title == pick_title,
        )
    )
    await db.commit()
    return {"status": "deleted"}
