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

from app.core.config import settings
from app.models.daily_report import DailyReport
from app.repositories.content_repo import ContentRepo
from app.repositories.ignored_repo import IgnoredRepo
from app.services.content_serialization import latest_analysis_from_item
from app.services.digest_base import is_active_generating as _digest_is_active_generating
from app.services.digest_fallback import build_daily_editorial_fallback
from app.services.llm import call_llm_json
from app.services.llm.prompts.daily_report import REPORT_PROMPT, SYSTEM_PROMPT
from app.services.scoring_engine import score_items
from app.services.scoring_inputs import build_scoring_inputs
from app.services.zhihu_url import normalize_zhihu_url
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)


WEEKDAYS = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
VALID_EDITIONS = {"snapshot", "noon", "evening", "final", "manual", "legacy"}
LOCAL_TZ = ZoneInfo("Asia/Shanghai")
GENERATING_STALE_AFTER = timedelta(minutes=10)

# 后端兜底校验常量（不信任 LLM 输出的枚举/字段约束）
_VALID_LIFECYCLE = {"上升期", "见顶", "退潮"}
_BRIEF_ALLOWED_FIELDS = {
    "source_idx",
    "source_title",
    "source_title_zh",
    "editorial_title",
    "title",
    "tier",
    "category",
    "reason",
    "platforms",
    "source_url",
    "score",
    "content_id",  # 站内阅读所需：ReaderDrawer 按 content_id 取正文
}


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


def _owner_filter(owner_user_id: int | None):
    """构建归属过滤子句（Postgres 安全）。

    ``None`` → 公共日报（``owner_user_id IS NULL``）；``int`` → 严格匹配该用户
    私有日报（``owner_user_id == <int>``）。与 ``DailyReportRepository._owner_clause``
    同口径——不能用 ``.is_(int)``，Postgres 的 ``IS`` 操作符不接受整数会报
    syntax error（SQLite 容忍故未暴露）。
    """
    if owner_user_id is None:
        return DailyReport.owner_user_id.is_(None)
    return DailyReport.owner_user_id == owner_user_id


def _is_active_generating(report: DailyReport, now: datetime) -> bool:
    """Delegate to digest_base.is_active_generating with DailyReport's generated_at field."""
    return _digest_is_active_generating(
        report,
        now,
        generated_at=_as_local_naive(report.generated_at) or _as_local_naive(report.updated_at),
    )


async def _fetch_report_inputs(
    db: AsyncSession,
    *,
    window_start: datetime,
    window_end: datetime,
    visible_user_id: int | None = None,
) -> tuple[list[dict], list[dict]]:
    repo = ContentRepo(db)
    query_start, query_end = _local_window_to_utc_naive(window_start, window_end)
    ignored_ids = await IgnoredRepo(db).list_ignored_ids()
    items = list(
        await repo.list_for_report_window(
            window_start=query_start,
            window_end=query_end,
            visible_user_id=visible_user_id,
            exclude_ids=ignored_ids,
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
        # 序号即 source_idx，模型按序号回引；URL 不喂给模型（由后端按 idx 注入，避免改写）。
        lines.append(f"\n{idx}. [{item['category']}] {item['title']}")
        lines.append(
            "   "
            f"来源: {item['source_name']} | "
            f"精选:{score:.1f} 创作:{item['creator_score']:.1f} "
            f"爆文:{item['viral_score']:.1f} 质量:{item['quality_score']:.1f} 风险:{item['risk_score']:.1f}"
        )
        if item.get("recommendation"):
            lines.append(f"   推荐: {str(item['recommendation'])[:150]}")
        if item.get("summary"):
            lines.append(f"   摘要: {str(item['summary'])[:200]}")
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
        .where(_owner_filter(owner_user_id))
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


def _match_picks_to_curated(
    raw_picks: list[dict],
    curated_for_prompt: list[dict],
) -> tuple[list[dict], list[int]]:
    """将 LLM 返回的 top_picks 匹配回精选素材，注入稳定字段并做后端兜底校验。

    匹配优先级：source_idx（精确）→ source_title 子串兜底 → URL 末位兜底。
    不信任 LLM 输出的枚举/字段约束，对 tier=lifecycle/angles 做白名单过滤。

    Args:
        raw_picks: LLM 返回的 top_picks 列表，每项含 source_idx / source_title / source_url 等。
        curated_for_prompt: 精选素材列表（已截断到 prompt 长度），每项含 id / title / url / score。

    Returns:
        (picks, selected_source_ids) — 匹配成功的 pick 列表 + 对应素材 id 列表。
    """
    matchable_items = curated_for_prompt
    curated_by_idx = {i + 1: item for i, item in enumerate(matchable_items)}
    curated_by_title = {item["title"]: item for item in matchable_items}
    curated_by_url = {normalize_zhihu_url(item.get("url", "")): item for item in matchable_items if item.get("url")}
    curated_titles = set(curated_by_title)
    selected_source_ids: list[int] = []
    picks: list[dict] = []
    for pick in raw_picks:
        matched_item: dict | None = None
        idx = pick.get("source_idx")
        if isinstance(idx, int):
            matched_item = curated_by_idx.get(idx)
        if not matched_item:
            source_title = pick.get("source_title", "")
            matched_title = next(
                (t for t in curated_titles if source_title and (source_title in t or t in source_title)),
                None,
            )
            matched_item = curated_by_title.get(matched_title) if matched_title else None
        if not matched_item:
            pick_url_norm = normalize_zhihu_url(pick.get("source_url", ""))
            matched_item = curated_by_url.get(pick_url_norm)
        if not matched_item:
            continue
        # 注入稳定字段：URL/title/score 由后端按匹配结果填，模型无需也不应改写。
        pick["source_url"] = normalize_zhihu_url(matched_item.get("url", ""))
        pick["source_title"] = pick.get("source_title") or matched_item["title"]
        pick["title"] = pick.get("editorial_title") or matched_item["title"]
        pick["score"] = round(float(matched_item.get("adjusted_score") or matched_item.get("curation_score") or 0))
        # 站内阅读：注入底层 content_id（= ContentItem.id），供前端 ReaderDrawer 取正文。
        # 在 feature/brief 分支之前注入，保证两条路径都带上；已加入 _BRIEF_ALLOWED_FIELDS。
        pick["content_id"] = matched_item["id"]
        # —— 后端兜底校验（不信任 LLM 输出的枚举/字段约束）——
        tier = pick.get("tier") or "feature"
        pick["tier"] = tier
        if tier == "brief":
            # brief 字段白名单：过滤掉 LLM 残留的 feature 专属字段
            pick = {k: v for k, v in pick.items() if k in _BRIEF_ALLOWED_FIELDS}
        else:
            # feature：生命周期没有足够依据时宁可不显示，也不伪造"上升期"。
            lc = pick.get("lifecycle")
            if lc in _VALID_LIFECYCLE:
                pick["lifecycle"] = lc
            else:
                pick.pop("lifecycle", None)
            # angles 过滤问句 + 限 3 条
            angles = pick.get("angles") or []
            pick["angles"] = [a for a in angles if isinstance(a, str) and not a.strip().endswith(("？", "?"))][:3]
        picks.append(pick)
        if matched_item["id"] not in selected_source_ids:
            selected_source_ids.append(matched_item["id"])
    return picks, selected_source_ids


def build_daily_report_card(
    report: DailyReport,
    picks: list[dict],
    report_date: str,
    normalized_edition: str,
) -> dict:
    """构建日报 webhook 卡片 payload（飞书 elements + 降级 markdown + 链接）。

    自动推送和手动推送共用此函数，保证格式一致。
    """
    overview_text = (report.overview or "")[:200]
    takeaway = (report.takeaway or "")[:60]

    # ── 飞书富卡片：takeaway + overview + 全部精选（feature 分层 + brief 速览）──
    # 当选题总数 ≤ 10 时全部展示，否则只展示 Top 10 + 汇总。
    max_display = 10
    show_count = min(len(picks), max_display)
    display_picks = picks[:show_count]

    # 按层级分组：feature 深度精讲，brief 速览
    feature_picks = [p for p in display_picks if p.get("tier") == "feature"]
    brief_picks = [p for p in display_picks if p.get("tier") != "feature"]

    feishu_elements: list[dict] = []

    # 1. takeaway — 一句话推送标题
    if takeaway:
        feishu_elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{takeaway}**"}})
        feishu_elements.append({"tag": "hr"})

    # 2. overview — 主编判断
    if overview_text:
        feishu_elements.append({"tag": "div", "text": {"tag": "lark_md", "content": overview_text}})

    # 3. 深度精讲 section
    if feature_picks:
        feishu_elements.append({"tag": "hr"})
        feishu_elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"🔥 **深度精讲**（{len(feature_picks)} 篇）"}}
        )
        for i, pick in enumerate(feature_picks, start=1):
            title = pick.get("editorial_title") or pick.get("source_title") or f"选题 {i}"
            category = pick.get("category", "")
            reason = (pick.get("reason") or "")[:120]
            angles = pick.get("angles") or []
            time_window = pick.get("time_window", "")
            source_url = pick.get("source_url") or ""

            meta_parts: list[str] = []
            if category:
                meta_parts.append(category)
            if time_window:
                meta_parts.append(f"⏰ {time_window}")
            meta_str = f" · {' · '.join(meta_parts)}" if meta_parts else ""
            feishu_elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**{i}. {title}**{meta_str}"}})
            if reason:
                feishu_elements.append({"tag": "note", "elements": [{"tag": "plain_text", "content": f"💡 {reason}"}]})
            if angles:
                angles_text = " | ".join(angles[:3])
                feishu_elements.append(
                    {"tag": "note", "elements": [{"tag": "plain_text", "content": f"✍️ {angles_text}"}]}
                )
            if source_url:
                feishu_elements.append(
                    {"tag": "div", "text": {"tag": "lark_md", "content": f"[📄 查看原文]({source_url})"}}
                )

    # 4. 速览 section
    if brief_picks:
        feishu_elements.append({"tag": "hr"})
        feishu_elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"📋 **速览**（{len(brief_picks)} 篇）"}}
        )
        brief_start = len(feature_picks) + 1
        for i, pick in enumerate(brief_picks, start=brief_start):
            title = pick.get("editorial_title") or pick.get("source_title") or f"选题 {i}"
            category = pick.get("category", "")
            source_url = pick.get("source_url") or ""
            meta_str = f" · {category}" if category else ""
            if source_url:
                meta_str += f" · [📄 原文]({source_url})"
            feishu_elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"{i}. {title}{meta_str}"}})

    # 5. 如果有更多未展示的
    if len(picks) > show_count:
        feishu_elements.append({"tag": "hr"})
        feishu_elements.append(
            {"tag": "div", "text": {"tag": "lark_md", "content": f"…共 {report.topic_count} 个选题，点击查看完整日报"}}
        )

    # 降级 markdown content（不支持卡片的平台用）
    card_content_parts: list[str] = []
    if takeaway:
        card_content_parts.append(takeaway)
    if overview_text:
        card_content_parts.append(overview_text)
    if feature_picks:
        card_content_parts.append(f"\n深度精讲（{len(feature_picks)} 篇）：")
        for i, pick in enumerate(feature_picks, start=1):
            title = pick.get("editorial_title") or pick.get("source_title") or f"选题 {i}"
            reason = (pick.get("reason") or "")[:80]
            source_url = pick.get("source_url") or ""
            url_str = f"  {source_url}" if source_url else ""
            card_content_parts.append(f"{i}. {title} — {reason}{url_str}")
    if brief_picks:
        card_content_parts.append(f"\n速览（{len(brief_picks)} 篇）：")
        brief_start = len(feature_picks) + 1
        for i, pick in enumerate(brief_picks, start=brief_start):
            title = pick.get("editorial_title") or pick.get("source_title") or f"选题 {i}"
            category = pick.get("category", "")
            source_url = pick.get("source_url") or ""
            cat_str = f" [{category}]" if category else ""
            url_str = f"  {source_url}" if source_url else ""
            card_content_parts.append(f"{i}. {title}{cat_str}{url_str}")
    if len(picks) > show_count:
        card_content_parts.append(f"\n…共 {report.topic_count} 个选题")
    card_content = "\n".join(p for p in card_content_parts if p)

    # 卡片链接：必须是绝对 URL（飞书按钮不支持相对路径）
    site_base = getattr(settings, "SITE_BASE_URL", "") or ""
    card_link = f"{site_base.rstrip('/')}/daily?date={report_date}" if site_base else ""

    return {
        "content": card_content,
        "link": card_link,
        "elements": feishu_elements,
        "button_text": "查看完整日报",
    }


async def push_daily_report_webhook(
    report: DailyReport,
    picks: list[dict],
    report_date: str,
    normalized_edition: str,
    *,
    force: bool = False,
) -> bool:
    """推送日报到 webhook（自动推送 / 手动推送共用）。

    Parameters
    ----------
    force : True 时跳过去重检查（手动推送场景）。

    Returns: True 如果发送成功，False 如果未配置或全部失败。
    """
    from app.services.alerting import send_alert

    card = build_daily_report_card(report, picks, report_date, normalized_edition)

    return await send_alert(
        title=f"📰 AI 日报 · {report_date} {_edition_label(normalized_edition)}",
        message=f"日报生成完成，共 {report.topic_count} 个选题",
        alert_key=f"daily_report:{report_date}:{normalized_edition}",
        severity="info",
        event_type="daily_report",
        card=card,
        force=force,
    )


async def _push_daily_report_success(
    report: DailyReport,
    picks: list[dict],
    report_date: str,
    normalized_edition: str,
) -> None:
    """日报生成成功后推送通知：站内 success 通知 + webhook 卡片。

    两条通道独立、互不阻塞，任一失败仅记录 warning，不影响主流程。
    """
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

    try:
        await push_daily_report_webhook(
            report,
            picks,
            report_date,
            normalized_edition,
            force=False,
        )
    except Exception:
        logger.warning("daily_report webhook push failed (non-fatal)", exc_info=True)


async def _push_daily_report_failure(exc: Exception) -> None:
    """日报生成失败时推送站内 error 通知。失败仅记录 warning，不抛出。"""
    try:
        from app.services.notification_service import push_notification

        await push_notification("error", "daily_report", "日报生成失败", str(exc)[:200])
    except Exception:
        logger.warning("daily_report failure notification failed", exc_info=True)


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
        existing_stmt = (
            select(DailyReport)
            .where(DailyReport.report_date == report_date)
            .where(DailyReport.edition == normalized_edition)
            .where(DailyReport.cutoff_at == window_end)
            .where(_owner_filter(owner_user_id))
            .with_for_update()
        )

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
                existing = await db.execute(existing_stmt.with_for_update())
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

    report, claimed = await _claim_generation()
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

    # 日报的可推荐选题只能来自精选池。背景素材只用于帮助归纳当天脉络，
    # 不能在精选为空时补位成日报推荐；否则会让“日报精选”的边界失真。
    if not curated_items:
        report.status = "DONE"
        report.overview = "今日暂未形成可推荐精选。已分析素材会继续参与后续评分，达到精选门槛后再进入日报。"
        report.takeaway = "今日暂无达到精选门槛的选题"
        report.keywords = json.dumps([], ensure_ascii=False)
        report.trends = json.dumps([], ensure_ascii=False)
        report.top_picks = json.dumps([], ensure_ascii=False)
        report.platform_tips = json.dumps({}, ensure_ascii=False)
        report.topic_count = 0
        report.source_item_ids = json.dumps([], ensure_ascii=False)
        report.updated_at = _local_now()
        await db.commit()
        return report

    # 截断一次：prompt 展示列表与下方匹配逻辑共用同一份，保证 source_idx 一致。
    curated_for_prompt = curated_items[:50]
    curated_text = _format_items(curated_for_prompt, limit=50, selected=True)
    background_text = _format_items(background_items, limit=80, selected=False)

    prompt = REPORT_PROMPT.format(
        date=report_date,
        weekday=weekday,
        edition_label=_edition_label(normalized_edition),
        window_start=window_start.strftime("%Y-%m-%d %H:%M"),
        window_end=window_end.strftime("%Y-%m-%d %H:%M"),
        curated_items_text=sanitize_prompt_input(curated_text, max_chars=6000),
        background_items_text=sanitize_prompt_input(background_text, max_chars=8000),
    )

    try:
        result = await call_llm_json(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            scene="daily_report",
            temperature=0.4,
            max_tokens=4000,
        )
        overview = result.get("overview", "")
        if not overview or "raw_response" in result:
            result = build_daily_editorial_fallback(
                curated_items,
                label=f"{report_date} {_edition_label(normalized_edition)}",
            )
            overview = result.get("overview", "")

        report.overview = overview
        report.takeaway = result.get("takeaway", "")
        report.keywords = json.dumps(result.get("keywords", []), ensure_ascii=False)
        report.trends = json.dumps(result.get("trends", []), ensure_ascii=False)

        raw_picks = result.get("top_picks", [])
        picks, selected_source_ids = _match_picks_to_curated(raw_picks, curated_for_prompt)

        report.top_picks = json.dumps(picks, ensure_ascii=False)
        report.platform_tips = json.dumps(result.get("platform_tips", {}), ensure_ascii=False)
        report.topic_count = len(picks)
        report.source_item_ids = json.dumps(
            selected_source_ids or [item["id"] for item in curated_items], ensure_ascii=False
        )
        report.status = "DONE"
        report.updated_at = _local_now()
        await db.commit()
        await _push_daily_report_success(report, picks, report_date, normalized_edition)
    except Exception as exc:
        report.status = "ERROR"
        report.overview = f"生成失败: {str(exc)[:200]}"
        report.source_item_ids = json.dumps([item["id"] for item in curated_items], ensure_ascii=False)
        await db.commit()
        await _push_daily_report_failure(exc)

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
