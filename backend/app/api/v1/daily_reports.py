"""
Daily Report API endpoints.
"""

from __future__ import annotations

import logging
from datetime import date as date_cls, datetime, timedelta
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import async_session, get_db
from app.repositories.content_repo import ContentRepo
from app.repositories.daily_report_repo import DailyReportRepository
from app.repositories.pick_mark_repo import PickMarkRepository
from app.schemas.daily_report import (
    DailyReportCalendarResponse,
    DailyReportDatesResponse,
    DailyReportListResponse,
    DailyReportResponse,
)
from app.services.daily_report import LOCAL_TZ, WEEKDAYS, generate_daily_report, get_latest_today_report
from app.services.plan_catalog import plan_allows_private_source

if TYPE_CHECKING:
    from app.models.user import User

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
    repo = DailyReportRepository(db)
    reports = await repo.list_for_calendar(start.isoformat(), today.isoformat())

    grouped: dict[str, list] = {}
    for report in reports:
        grouped.setdefault(report.report_date, []).append(report)

    calendar_statuses = {"DONE", "ERROR", "GENERATING", "MISSING"}

    def pick_calendar_report(items: list, current_date: date_cls) -> tuple:
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
    repo = DailyReportRepository(db)
    total = await repo.count_all()
    items = await repo.list_recent_with_limit(limit)

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

    from app.services.daily_report import _day_window, _local_today, _local_window_to_utc_naive

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
    repo = DailyReportRepository(db)
    report = await repo.find_existing_for_version(
        report_date_iso=parsed_date.isoformat(),
        edition=normalized_edition,
        owner_user_id=None,
    )

    if report and report.status == "DONE" and not force:
        return report

    if report:
        repo.mark_generating(report)
    else:
        report = repo.create_generating_placeholder(
            report_date_iso=parsed_date.isoformat(),
            weekday=WEEKDAYS[parsed_date.weekday()],
            edition=normalized_edition,
            window_start=utc_start,
            window_end=utc_end,
            cutoff_at=parsed_cutoff,
        )

    await repo.commit()
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
                    bg_repo = DailyReportRepository(bg_db)
                    await bg_repo.mark_error(report_id, f"生成失败: {str(e)[:200]}")
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


@router.post("/push-webhook")
async def push_daily_report_webhook(
    date: str = Query(..., description="Report date in YYYY-MM-DD format"),
    edition: str | None = Query(None, description="Optional edition filter"),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """手动推送指定日期的日报到已配置的 webhook。

    仅管理员可调用。使用 force=True 跳过自动推送的去重检查。
    如果该日报尚未生成或生成中，返回 400。
    """
    import json as _json

    from app.services.daily_report import push_daily_report_webhook as _push

    repo = DailyReportRepository(db)
    report = await repo.get_by_date(date, edition=edition)
    if report is None:
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的日报")
    if report.status != "DONE":
        raise HTTPException(status_code=400, detail=f"日报状态为 {report.status}，无法推送")

    picks = _json.loads(report.top_picks) if report.top_picks else []
    sent = await _push(
        report,
        picks,
        report.report_date,
        report.edition,
        force=True,
    )
    if not sent:
        return {"sent": False, "message": "未配置 webhook 或发送失败，请检查通知配置"}
    return {"sent": True, "message": f"日报已推送到群（{report.report_date} {report.edition}）"}


def _extract_sparkline_keywords(title: str, limit: int = 4) -> list[str]:
    """从选题标题里提取 1-4 个最具区分度的关键词供 sparkline 查询。

    - 中文走 jieba 切词，英文/数字按 regex 切
    - 去除常见停用词 + 单字无意义词
    - 按长度排序优先长词（专有名词通常更长），去重后取前 N 个
    """
    import re as _re

    if not title:
        return []
    stopwords = {
        "的",
        "了",
        "在",
        "是",
        "和",
        "与",
        "或",
        "为",
        "我",
        "你",
        "他",
        "她",
        "它",
        "也",
        "都",
        "就",
        "把",
        "被",
        "着",
        "the",
        "a",
        "an",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "for",
        "with",
    }
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
    keywords = _extract_sparkline_keywords(title)
    if not keywords:
        return {"points": [], "keywords": [], "total": 0, "window_hours": hours}

    cutoff = datetime.now() - timedelta(hours=hours)
    content_repo = ContentRepo(db)
    raw = await content_repo.count_hourly_by_title_keywords(keywords, cutoff)

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
    sorted_buckets[-1]
    # 对齐到当前时刻
    now_bucket = int(datetime.now().timestamp() // bucket_seconds)
    points: list[dict] = []
    for b in range(min_bucket, now_bucket + 1):
        ts_dt = datetime.fromtimestamp(b * bucket_seconds)
        points.append(
            {
                "ts": ts_dt.isoformat(),
                "count": bucket_counts.get(b, 0),
            }
        )

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


# ── 昨日追踪（一期补连续性闭环）──────────────────────────────


def _pick_key(pick: dict) -> str:
    """选题稳定键：优先 source_title（跨版本稳定），回退 title。与前端 pickKey 对齐。"""
    return pick.get("source_title") or pick.get("title") or ""


def _lifecycle_status(
    yesterday_lc: str | None,
    today_lc: str | None,
    on_board_today: bool,
) -> str:
    """判定昨日选题今日的状态。

    - ``confirmed``：上升期今日转见顶或仍上升期（趋势兑现）
    - ``reversed``：上升期今日转退潮（趋势反转）
    - ``persisted``：仍在榜但无 lifecycle 变化可判断
    - ``dropped``：今日已掉出榜单
    """
    if not on_board_today:
        return "dropped"
    if yesterday_lc == "上升期":
        if today_lc == "退潮":
            return "reversed"
        if today_lc in ("见顶", "上升期"):
            return "confirmed"
    return "persisted"


def _heat_delta_pct(
    raw: list[tuple[datetime, int]],
    *,
    today_iso: str,
) -> float | None:
    """根据 sparkline pipeline 返回的小时桶数据，算「昨日 vs 今日」热度变化率。

    取昨日桶均值作 baseline，今日桶均值作对比，返回百分比变化：
    (today_avg - yesterday_avg) / max(1, yesterday_avg) * 100。
    任一侧无数据返回 None（前端显示「—」）。
    """
    if not raw:
        return None
    yesterday_counts: list[int] = []
    today_counts: list[int] = []
    for ts, cnt in raw:
        if ts.date().isoformat() == today_iso:
            today_counts.append(cnt)
        else:
            yesterday_counts.append(cnt)
    if not yesterday_counts or not today_counts:
        return None
    y_avg = sum(yesterday_counts) / len(yesterday_counts)
    t_avg = sum(today_counts) / len(today_counts)
    if y_avg <= 0:
        return None
    return round((t_avg - y_avg) / y_avg * 100, 1)


async def _build_yesterday_tracking(
    db: AsyncSession,
    *,
    today_report,
    report_repo: DailyReportRepository,
    content_repo: ContentRepo,
    owner_user_id: int | None = None,
    user_id: int | None = None,
) -> dict:
    """组装昨日追踪卡数据。纯只读，不改任何数据。

    复用既有资产：DailyReport.source_item_ids / top_picks、ContentRepo
    .count_hourly_by_title_keywords（sparkline pipeline）、PickMarkRepository
    （周报 pick-tracking）。不引入新表/字段。
    """
    # 1. 算昨天日期（基于今日报告日期，避免跨时区漂移）
    try:
        today_date = datetime.fromisoformat(today_report.report_date).date()
    except (ValueError, TypeError):
        today_date = datetime.now(LOCAL_TZ).date()
    yesterday_iso = (today_date - timedelta(days=1)).isoformat()

    yesterday_report = await report_repo.get_yesterday_report(yesterday_iso, owner_user_id=owner_user_id)
    base: dict = {
        "has_yesterday": False,
        "report_date": yesterday_iso,
        "picks": [],
        "your_marked": [],
    }
    if not yesterday_report:
        return base

    # 2. 解析昨日 top_picks
    try:
        yesterday_picks = _safe_json_loads(yesterday_report.top_picks) or []
    except Exception:
        yesterday_picks = []
    if not yesterday_picks:
        return base

    base["has_yesterday"] = True

    # 3. 今日上榜 source_title 集合（用于 dropped 判定 + 今日 lifecycle/score）
    try:
        today_picks = _safe_json_loads(today_report.top_picks) or []
    except Exception:
        today_picks = []
    today_by_key: dict[str, dict] = {}
    for tp in today_picks:
        key = _pick_key(tp)
        if key:
            today_by_key[key] = tp

    # 4. 组装每个昨日 pick 的追踪项
    items: list[dict] = []
    for rank, yp in enumerate(yesterday_picks):
        key = _pick_key(yp)
        if not key:
            continue
        today_pick = today_by_key.get(key)
        on_board_today = today_pick is not None
        yesterday_lc = yp.get("lifecycle")
        today_lc = today_pick.get("lifecycle") if today_pick else None

        # 热度 delta：复用 sparkline pipeline（48h 覆盖昨日+今日）
        keywords = _extract_sparkline_keywords(yp.get("source_title") or yp.get("title") or "")
        heat_delta = None
        if keywords:
            cutoff = datetime.now() - timedelta(hours=48)
            raw = await content_repo.count_hourly_by_title_keywords(keywords, cutoff)
            heat_delta = _heat_delta_pct(raw, today_iso=today_report.report_date)

        items.append(
            {
                "title": yp.get("title") or yp.get("source_title") or "",
                "source_title": yp.get("source_title") or "",
                "rank": rank,
                "old_score": yp.get("score"),
                "yesterday_lifecycle": yesterday_lc,
                "today_score": today_pick.get("score") if today_pick else None,
                "today_lifecycle": today_lc,
                "heat_delta_pct": heat_delta,
                "status": _lifecycle_status(yesterday_lc, today_lc, on_board_today),
            }
        )
    base["picks"] = items

    # 5. scope=mine 时，附「我标过的」昨日选题进展（二期个性化的数据预留）
    if user_id is not None:
        from datetime import date as date_type

        mark_repo = PickMarkRepository(db)
        marks = await mark_repo.list_by_user(user_id, date_type.fromisoformat(yesterday_iso))
        # 复用与 picks 相同的今日匹配逻辑
        for m in marks:
            if m.action == "skip":
                continue
            key = m.pick_title
            today_pick = today_by_key.get(key)
            on_board_today = today_pick is not None
            base["your_marked"].append(
                {
                    "title": m.pick_title,
                    "mark": m.action,
                    "category": m.pick_category,
                    "today_score": today_pick.get("score") if today_pick else None,
                    "today_lifecycle": today_pick.get("lifecycle") if today_pick else None,
                    "status": "dropped" if not on_board_today else "persisted",
                }
            )

    return base


def _safe_json_loads(value) -> list | dict | None:
    """容忍 None / 已是 list / JSON 字符串三种情况。"""
    if value is None:
        return None
    if isinstance(value, list | dict):
        return value
    import json

    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return None


@router.get("/yesterday-tracking")
async def get_yesterday_tracking(
    report_date: str = Query(..., description="今日报告日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """昨日 top picks 的 24h 热度 delta + lifecycle 验证（公共日报）。

    纯只读聚合，不改数据。无昨日报告返回 ``{has_yesterday: false}``。
    """
    return await _build_yesterday_tracking_public(db, report_date=report_date, owner_user_id=None)


@router.get("/me/yesterday-tracking")
async def get_my_yesterday_tracking(
    report_date: str = Query(..., description="今日报告日期 YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """昨日追踪（我的日报，Pro+）。额外返回 your_marked（昨日 write/watch 标记的今日进展）。"""
    if not plan_allows_private_source(user.plan):
        raise HTTPException(status_code=403, detail="我的日报需 Pro 及以上套餐")
    return await _build_yesterday_tracking_public(db, report_date=report_date, owner_user_id=user.id, user_id=user.id)


async def _build_yesterday_tracking_public(
    db: AsyncSession,
    *,
    report_date: str,
    owner_user_id: int | None,
    user_id: int | None = None,
) -> dict:
    """昨日追踪组装的公共路径：取今日报告 → 取昨日报告 → 组装。"""
    import types

    report_repo = DailyReportRepository(db)
    content_repo = ContentRepo(db)
    # 今日报告：按传入日期取（final 优先，回退最新），不触发生成
    today_report = await report_repo.get_by_date(report_date, owner_user_id=owner_user_id)
    if today_report is None:
        # 无今日报告时仍可追踪昨日（picks 里 today_*=null）。
        # 用 SimpleNamespace 而非内联 class，避免类体名字解析捕获不到函数参数。
        today_report = types.SimpleNamespace(report_date=report_date, top_picks=None)
    return await _build_yesterday_tracking(
        db,
        today_report=today_report,
        report_repo=report_repo,
        content_repo=content_repo,
        owner_user_id=owner_user_id,
        user_id=user_id,
    )


# ── 选题标记（写这个/观察/跳过）──────────────────────────────


@router.get("/pick-marks")
async def list_pick_marks(
    report_date: str = Query(None, description="按日期过滤（YYYY-MM-DD）"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """获取用户的选题标记列表。"""
    from datetime import date as date_type

    parsed_date = date_type.fromisoformat(report_date) if report_date else None
    repo = PickMarkRepository(db)
    marks = await repo.list_by_user(user.id, parsed_date)
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
    repo = PickMarkRepository(db)
    mark = await repo.find_existing(user.id, parsed_date, pick_title)
    if mark:
        repo.update_mark(
            mark,
            action=action,
            pick_category=pick_category,
            pick_source_url=pick_source_url,
        )
    else:
        repo.add_new(
            user_id=user.id,
            report_date=parsed_date,
            pick_title=pick_title,
            action=action,
            pick_category=pick_category,
            pick_source_url=pick_source_url,
        )
    await repo.commit()
    return {"status": "ok", "action": action}


@router.delete("/pick-marks")
async def delete_pick_mark(
    report_date: str = Query(...),
    pick_title: str = Query(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """删除选题标记。"""
    from datetime import date as date_type

    parsed_date = date_type.fromisoformat(report_date)
    repo = PickMarkRepository(db)
    await repo.delete_by_user_date_title(user.id, parsed_date, pick_title)
    await repo.commit()
    return {"status": "deleted"}


@router.get("/webhook-logs")
async def list_webhook_delivery_logs(
    event_type: str | None = Query(None, description="Filter by event type"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_current_admin_user),
):
    """List webhook delivery logs (admin only)."""
    from app.repositories.webhook_delivery_log_repo import WebhookDeliveryLogRepository

    repo = WebhookDeliveryLogRepository(db)
    logs, total = await repo.list_recent(event_type=event_type, limit=limit, offset=offset)

    return {
        "items": [
            {
                "id": log.id,
                "alert_key": log.alert_key,
                "event_type": log.event_type,
                "title": log.title,
                "severity": log.severity,
                "webhook_url_preview": log.webhook_url_preview,
                "status_code": log.status_code,
                "success": bool(log.success),
                "error_message": log.error_message,
                "response_preview": log.response_preview,
                "duration_ms": log.duration_ms,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
