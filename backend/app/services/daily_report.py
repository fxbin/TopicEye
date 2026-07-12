"""
Daily Report service — generate versioned daily snapshots and final editions.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_profile
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.daily_report import DailyReport
from app.repositories.content_repo import ContentRepo
from app.services.content_serialization import latest_analysis_from_item
from app.services.digest_fallback import build_digest_fallback
from app.services.llm import call_llm_json
from app.services.scoring_engine import score_items
from app.services.scoring_inputs import build_scoring_inputs
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)


WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
VALID_EDITIONS = {"snapshot", "noon", "evening", "final", "manual", "legacy"}
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GENERATING_STALE_AFTER = timedelta(minutes=10)

REPORT_PROMPT = """你是一位资深内容策划顾问。请根据以下「精选内容」和「全天候选背景」，生成一份面向创作者的日报。

## 日报窗口
- 日期：{date}（{weekday}）
- 版本：{edition_label}
- 统计窗口：{window_start} ~ {window_end}

## 精选内容（用于 top_picks，只能从这里选）
{curated_items_text}

## 今日候选背景（用于 overview / trends / keywords，不要直接作为 top_picks）
{background_items_text}

## 请严格按以下 JSON 格式输出：
{{
  "overview": "一段200字以内的今日热点概述，用轻松专业的口吻，点出今日最值得关注的方向",
  "takeaway": "一句话核心要点，适合作为日报标题/推送文案",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5"],
  "trends": [
    {{"title": "趋势标题", "desc": "趋势描述（30字内）", "color": "#3B82F6", "momentum": "up"}}
  ],
  "top_picks": [
    {{
      "title": "选题标题",
      "reason": "中文摘要式推荐理由（40字内，概括核心信息+为什么值得写）",
      "source_url": "原文链接URL",
      "score": 85,
      "platforms": ["公众号", "小红书"],
      "angles": ["具体创作角度1（15字内）", "具体创作角度2（15字内）"],
      "pitfall": "避坑提示（20字内，指出时效/争议/信息不足等风险）",
      "lifecycle": "上升期",
      "time_window": "建议48h内发布"
    }}
  ],
  "platform_tips": {{
    "公众号": ["tip1"],
    "小红书": ["tip1"],
    "视频号": ["tip1"]
  }}
}}

要求：
- top_picks 从「精选内容」中选 3-5 个最值得写的选题，source_url 必须复制原始URL，不要编造
- top_picks.reason 必须是中文摘要式推荐理由：先概括这条内容讲了什么，再说明为什么值得写；不要输出英文、不要营销夸张词、不要只写"建议关注/可以写"
- top_picks.angles: 1-2个差异化的创作角度，每个15字内，要具体可操作（如"MCP实操教程""Agent vs Workflow对比"）
- top_picks.pitfall: 指出这个选题的风险或注意点（如"官方文档不全""争议性话题注意立场"）
- top_picks.lifecycle: 从"上升期"/"见顶"/"退潮"三选一，判断话题热度阶段
- top_picks.time_window: 发布时间建议（如"建议48h内发布""可周末发"）
- trends.momentum: 从"up"/"down"/"stable"三选一
- overview / trends / keywords 可以结合候选背景判断今天的整体方向
- 如果精选内容较少，就少选，不要从候选背景中硬凑
- 所有文本用中文
- 只输出 JSON，不要其他内容"""


def _local_now() -> datetime:
    return datetime.now(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def _local_today() -> date:
    return _local_now().date()


def _as_local_naive(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(microsecond=0)
    return value.astimezone(LOCAL_TZ).replace(tzinfo=None, microsecond=0)


def _local_window_to_utc_naive(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """Convert local report-display window to storage/query window."""
    return (
        start.replace(tzinfo=LOCAL_TZ).astimezone(UTC).replace(tzinfo=None),
        end.replace(tzinfo=LOCAL_TZ).astimezone(UTC).replace(tzinfo=None),
    )


def _day_window(target: date, cutoff_at: datetime | None, edition: str) -> tuple[datetime, datetime]:
    start = datetime.combine(target, time.min)
    if edition == "final":
        return start, datetime.combine(target, time.max).replace(microsecond=0)

    if cutoff_at is None:
        cutoff_at = _local_now()
    cutoff_at = _as_local_naive(cutoff_at)
    # A same-day snapshot is always bounded to that date.
    end = min(cutoff_at.replace(microsecond=0), datetime.combine(target, time.max).replace(microsecond=0))
    if end < start:
        end = datetime.combine(target, time.max).replace(microsecond=0)
    return start, end


def _edition_for_now(now: datetime | None = None) -> str:
    now = _as_local_naive(now) or _local_now()
    if now.hour < 14:
        return "noon"
    if now.hour < 22:
        return "evening"
    return "snapshot"


def _edition_label(edition: str) -> str:
    return {
        "noon": "午间快照",
        "evening": "晚间快照",
        "final": "完整复盘",
        "manual": "手动快照",
        "snapshot": "实时快照",
        "legacy": "历史日报",
    }.get(edition, edition)


def _normalize_edition(edition: str | None, target: date, cutoff_at: datetime | None) -> str:
    if edition:
        normalized = edition.lower()
        if normalized not in VALID_EDITIONS:
            raise ValueError(f"Unsupported daily report edition: {edition}")
        return normalized

    today = _local_today()
    if target < today:
        return "final"
    return _edition_for_now(cutoff_at)


def _is_active_generating(report: DailyReport, now: datetime) -> bool:
    if report.status != "GENERATING":
        return False
    generated_at = _as_local_naive(report.generated_at) or _as_local_naive(report.updated_at) or now
    return now - generated_at < GENERATING_STALE_AFTER


async def _fetch_report_inputs(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    visible_user_id: int | None = None,
) -> tuple[list[dict], list[dict]]:
    repo = ContentRepo(db)
    query_start, query_end = _local_window_to_utc_naive(window_start, window_end)
    items = list(
        await repo.list_for_report_window(
            window_start=query_start,
            window_end=query_end,
            visible_user_id=visible_user_id,
        )
    )
    scoring_inputs, item_map, _ = await build_scoring_inputs(db, items)
    scored = score_items(scoring_inputs) if scoring_inputs else []

    curated: list[dict] = []
    for breakdown, si in scored:
        item = item_map.get(si.content_id)
        if not item:
            continue
        analysis = latest_analysis_from_item(item)
        if analysis is None:
            continue
        record = _item_to_report_dict(item, analysis, breakdown.final_score)
        if breakdown.selected:
            curated.append(record)

    # If the window is sparse, still provide a few high-quality analyzed items as context,
    # but top_picks will be instructed to use only selected curated items.
    background = [
        _item_to_report_dict(item, analysis, analysis.curation_score or 0)
        for item in items
        if (analysis := latest_analysis_from_item(item)) is not None
    ]
    background.sort(key=lambda x: (x["curation_score"], x["creator_score"]), reverse=True)
    curated.sort(key=lambda x: (x["adjusted_score"], x["curation_score"]), reverse=True)
    return curated, background


def _item_to_report_dict(item, analysis, adjusted_score: float) -> dict:
    return {
        "id": item.id,
        "title": item.title,
        "url": normalize_zhihu_url(item.url),
        "category": item.category or "未分类",
        "source_name": item.source_name or "",
        "creator_score": analysis.creator_score or 0,
        "viral_score": analysis.viral_score or 0,
        "quality_score": analysis.quality_score or 0,
        "risk_score": analysis.risk_score or 0,
        "curation_score": analysis.curation_score or 0,
        "adjusted_score": round(float(adjusted_score or 0), 1),
        "summary": analysis.summary or item.summary or "",
        "recommendation": analysis.recommendation or analysis.recommended_reason or "",
    }


def _format_items(items: list[dict], *, limit: int, selected: bool) -> str:
    if not items:
        return "暂无"

    lines: list[str] = []
    for idx, item in enumerate(items[:limit], 1):
        score = item.get("adjusted_score") if selected else item.get("curation_score")
        lines.append(f"\n{idx}. [{item['category']}] {item['title']}")
        lines.append(
            "   "
            f"来源: {item['source_name']} | URL: {item.get('url', '')} | "
            f"精选:{score:.1f} 创作:{item['creator_score']:.1f} "
            f"爆文:{item['viral_score']:.1f} 质量:{item['quality_score']:.1f} 风险:{item['risk_score']:.1f}"
        )
        if item.get("recommendation"):
            lines.append(f"   推荐: {str(item['recommendation'])[:100]}")
        if item.get("summary"):
            lines.append(f"   摘要: {str(item['summary'])[:120]}")
    return "\n".join(lines)


async def get_latest_today_report(
    db: AsyncSession,
    *,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Return today's newest report, generating a snapshot if none exists.

    ``owner_user_id``: ``None`` → public (NULL) report; ``int`` → strictly the
    user's own report. Pass the user's id for the /me endpoints.
    """
    today = _local_today().isoformat()
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.report_date == today)
        .where(DailyReport.owner_user_id.is_(owner_user_id))
        .order_by(DailyReport.cutoff_at.desc(), DailyReport.updated_at.desc())
        .limit(1)
    )
    report = result.scalar_one_or_none()
    if report:
        return report
    return await generate_daily_report(
        db,
        target_date=_local_today(),
        edition=_edition_for_now(),
        owner_user_id=owner_user_id,
    )


async def generate_daily_report(
    db: AsyncSession,
    *,
    target_date: date | None = None,
    edition: str | None = None,
    cutoff_at: datetime | None = None,
    force: bool = False,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Generate a versioned daily report for a precise time window.

    ``owner_user_id``: ``None`` → public report; ``int`` → user-owned report.
    Pass the user's id for the /me endpoints.
    """
    target = target_date or _local_today()
    normalized_edition = _normalize_edition(edition, target, cutoff_at)
    window_start, window_end = _day_window(target, cutoff_at, normalized_edition)
    report_date = target.isoformat()
    weekday = WEEKDAYS[target.weekday()]
    now = _local_now()

    async def _claim_generation() -> tuple[DailyReport, bool]:
        if database_profile.is_sqlite:
            await begin_immediate_for_sqlite(db)

        existing_stmt = (
            select(DailyReport)
            .where(DailyReport.report_date == report_date)
            .where(DailyReport.edition == normalized_edition)
            .where(DailyReport.cutoff_at == window_end)
            .where(DailyReport.owner_user_id.is_(owner_user_id))
        )
        if database_profile.is_postgresql:
            existing_stmt = existing_stmt.with_for_update()

        existing = await db.execute(existing_stmt)
        report = existing.scalar_one_or_none()
        if report and report.status == "DONE" and not force:
            return report, False
        if report and _is_active_generating(report, now) and not force:
            return report, False

        if not report:
            report = DailyReport(
                report_date=report_date,
                weekday=weekday,
                edition=normalized_edition,
                generated_at=now,
                window_start=window_start,
                window_end=window_end,
                cutoff_at=window_end,
                source_scope="curated",
                status="GENERATING",
                content_count=0,
                analyzed_count=0,
                owner_user_id=owner_user_id,
            )
            db.add(report)
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                existing = await db.execute(
                    existing_stmt.with_for_update() if database_profile.is_postgresql else existing_stmt
                )
                report = existing.scalar_one()
                if report.status == "DONE" and not force:
                    return report, False
                if _is_active_generating(report, _local_now()) and not force:
                    return report, False
                report.status = "GENERATING"
                report.generated_at = _local_now()
                await db.flush()
        else:
            report.status = "GENERATING"
            report.generated_at = now
            report.window_start = window_start
            report.window_end = window_end
            report.cutoff_at = window_end
            await db.flush()

        return report, True

    report, claimed = await retry_sqlite_locked(
        _claim_generation,
        attempts=4,
        base_delay=0.1,
        on_retry=db.rollback,
    )
    if not claimed:
        return report

    await db.commit()

    curated_items, background_items = await _fetch_report_inputs(
        db,
        window_start=window_start,
        window_end=window_end,
        visible_user_id=owner_user_id,
    )
    report.content_count = len(background_items)
    report.analyzed_count = len(background_items)
    await db.flush()

    if not background_items:
        report.status = "ERROR"
        report.overview = "当前窗口暂无分析数据，请先同步信源并等待 AI 分析完成。"
        report.source_item_ids = json.dumps([], ensure_ascii=False)
        await db.commit()
        return report

    curated_text = _format_items(curated_items, limit=50, selected=True)
    background_text = _format_items(background_items, limit=80, selected=False)

    prompt = REPORT_PROMPT.format(
        date=report_date,
        weekday=weekday,
        edition_label=_edition_label(normalized_edition),
        window_start=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end=window_end.strftime("%Y-%m-%d %H:%M"),
        curated_items_text=curated_text,
        background_items_text=background_text,
    )

    try:
        result = await call_llm_json([{"role": "user", "content": prompt}], scene="daily_report")
        overview = result.get("overview", "")
        if not overview or "raw_response" in result:
            fallback_items = curated_items or background_items
            result = build_digest_fallback(fallback_items, label=f"{report_date} {_edition_label(normalized_edition)}")
            overview = result.get("overview", "")

        report.overview = overview
        report.takeaway = result.get("takeaway", "")
        report.keywords = json.dumps(result.get("keywords", []), ensure_ascii=False)
        report.trends = json.dumps(result.get("trends", []), ensure_ascii=False)

        raw_picks = result.get("top_picks", [])
        picks = []
        curated_by_title = {item["title"]: item for item in curated_items}
        curated_by_url = {normalize_zhihu_url(item.get("url", "")): item for item in curated_items if item.get("url")}
        curated_titles = set(curated_by_title)
        selected_source_ids: list[int] = []
        for pick in raw_picks:
            if not curated_titles:
                break
            pick_title = pick.get("title", "")
            pick_url = normalize_zhihu_url(pick.get("source_url", ""))
            matched_title = next(
                (title for title in curated_titles if pick_title and (pick_title in title or title in pick_title)),
                None,
            )
            matched_item = curated_by_title.get(matched_title) if matched_title else curated_by_url.get(pick_url)
            if not matched_item:
                continue
            if pick_url:
                pick["source_url"] = pick_url
            if not pick_url or not pick_url.startswith("http"):
                fallback_url = normalize_zhihu_url(matched_item.get("url", ""))
                if fallback_url:
                    pick["source_url"] = fallback_url
            picks.append(pick)
            if matched_item["id"] not in selected_source_ids:
                selected_source_ids.append(matched_item["id"])

        report.top_picks = json.dumps(picks, ensure_ascii=False)
        report.platform_tips = json.dumps(result.get("platform_tips", {}), ensure_ascii=False)
        report.topic_count = len(picks)
        report.source_item_ids = json.dumps(
            selected_source_ids or [item["id"] for item in curated_items], ensure_ascii=False
        )
        report.status = "DONE"
        report.updated_at = _local_now()
        await db.commit()
        try:
            from app.services.notification_service import push_notification

            await push_notification(
                "success",
                "daily_report",
                "日报生成完成",
                f"{report_date} {_edition_label(normalized_edition)}，共 {report.topic_count} 个选题",
            )
        except Exception:
            logger.warning("daily_report success notification failed", exc_info=True)
    except Exception as exc:
        report.status = "ERROR"
        report.overview = f"生成失败: {str(exc)[:200]}"
        report.source_item_ids = json.dumps([item["id"] for item in curated_items], ensure_ascii=False)
        await db.commit()
        try:
            from app.services.notification_service import push_notification

            await push_notification("error", "daily_report", "日报生成失败", str(exc)[:200])
        except Exception:
            logger.warning("daily_report failure notification failed", exc_info=True)

    return report


async def generate_previous_day_final_report(
    db: AsyncSession,
    *,
    force: bool = False,
    owner_user_id: int | None = None,
) -> DailyReport:
    """Generate yesterday's final full-day edition."""
    yesterday = _local_today() - timedelta(days=1)
    return await generate_daily_report(
        db,
        target_date=yesterday,
        edition="final",
        force=force,
        owner_user_id=owner_user_id,
    )
