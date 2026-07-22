"""
Weekly Digest service — generate AI-powered weekly curated newsletter.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_profile
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.core.time import utc_now
from app.models.weekly_digest import WeeklyDigest
from app.services.digest_base import (
    apply_llm_result,
    apply_llm_result_with_matching,
    commit_digest_error,
    is_active_generating,
    push_digest_notification,
)
from app.services.digest_context import (
    build_category_stats,
    build_category_text,
    build_items_text,
    fetch_analyzed_content,
)
from app.services.digest_fallback import build_digest_fallback
from app.services.llm import call_llm_json
from app.services.llm.prompts.weekly_digest import WEEKLY_DIGEST_PROMPT

logger = logging.getLogger(__name__)


def _get_week_range(reference_date: date | None = None) -> tuple[str, str, str, str]:
    """Return (week_key, week_label, week_start_iso, week_end_iso) for a given date's week.

    Week runs Monday–Sunday (ISO week).
    week_key format: "2025-W21"
    week_label format: "5月19日 ~ 5月25日"
    """
    d = reference_date or date.today()
    iso_cal = d.isocalendar()
    week_key = f"{iso_cal[0]}-W{iso_cal[1]:02d}"

    # Monday of this week
    monday = d - timedelta(days=d.weekday())
    sunday = monday + timedelta(days=6)

    def _fmt(dt: date) -> str:
        return f"{dt.month}月{dt.day}日"

    week_label = f"{_fmt(monday)} ~ {_fmt(sunday)}"
    return week_key, week_label, monday.isoformat(), sunday.isoformat()


async def _fetch_weekly_analyzed(db: AsyncSession, week_start: str, week_end: str) -> list[dict]:
    """Fetch analyzed content items within the given week range through DuckDB."""
    return await fetch_analyzed_content(db, week_start, week_end)


def _build_category_stats(items: list[dict]) -> dict:
    """Build category-level statistics from items."""
    return build_category_stats(items)


def _is_active_generating(digest: WeeklyDigest, now: datetime) -> bool:
    return is_active_generating(digest, now)


async def generate_weekly_digest(
    db: AsyncSession,
    reference_date: date | None = None,
) -> WeeklyDigest:
    """Generate (or regenerate) the weekly digest for the PREVIOUS week.

    By default, generates last week's digest (Monday–Sunday).
    If reference_date is provided, uses that date's previous week.

    Args:
        db: Database session.
        reference_date: The date whose PREVIOUS ISO week to generate for. Defaults to today.

    Returns:
        The WeeklyDigest record (may have status ERROR if generation failed).
    """
    # Use PREVIOUS week, not current week
    d = reference_date or date.today()
    last_week_date = d - timedelta(days=7)
    week_key, week_label, week_start, week_end = _get_week_range(last_week_date)
    now = utc_now()

    async def _claim_generation() -> tuple[WeeklyDigest, bool]:
        if database_profile.is_sqlite:
            await begin_immediate_for_sqlite(db)

        existing_stmt = select(WeeklyDigest).where(WeeklyDigest.week_key == week_key)
        if database_profile.is_postgresql:
            existing_stmt = existing_stmt.with_for_update()

        existing = await db.execute(existing_stmt)
        digest = existing.scalar_one_or_none()
        if digest and digest.status == "DONE":
            return digest, False
        if digest and _is_active_generating(digest, now):
            return digest, False

        if not digest:
            digest = WeeklyDigest(
                week_key=week_key,
                week_label=week_label,
                week_start=week_start,
                week_end=week_end,
                status="GENERATING",
            )
            db.add(digest)
            try:
                await db.flush()
            except IntegrityError:
                await db.rollback()
                existing = await db.execute(
                    existing_stmt.with_for_update() if database_profile.is_postgresql else existing_stmt
                )
                digest = existing.scalar_one()
                if digest.status == "DONE":
                    return digest, False
                if _is_active_generating(digest, utc_now()):
                    return digest, False
                digest.status = "GENERATING"
                await db.flush()
        else:
            digest.status = "GENERATING"
            await db.flush()

        return digest, True

    digest, claimed = await retry_sqlite_locked(
        _claim_generation,
        attempts=4,
        base_delay=0.1,
        on_retry=db.rollback,
    )
    if not claimed:
        return digest

    await db.commit()

    # Fetch this week's analyzed content
    items_data = await _fetch_weekly_analyzed(db, week_start, week_end)

    # If no data for the strict ISO week, expand to the last 7 days
    if not items_data:
        expanded_start = (date.fromisoformat(week_end) - timedelta(days=6)).isoformat()
        items_data = await _fetch_weekly_analyzed(db, expanded_start, week_end)
        if items_data:
            logger.info(
                "Weekly digest: no data for ISO week %s, expanded to %s ~ %s (%d items)",
                week_key,
                expanded_start,
                week_end,
                len(items_data),
            )

    if not items_data:
        digest.status = "ERROR"
        digest.overview = "本周暂无分析数据，请先同步信源并等待 AI 分析完成。"
        await db.commit()
        return digest

    # Build items text for prompt (top 25)
    items_text = build_items_text(items_data, limit=25)

    # Build category stats text
    cat_stats = _build_category_stats(items_data)
    category_text = build_category_text(cat_stats)

    prompt = WEEKLY_DIGEST_PROMPT.format(
        week_label=week_label,
        items_text=items_text,
        category_text=category_text,
    )

    digest.content_count = len(items_data)
    digest.analyzed_count = len(items_data)
    digest.source_count = len({x["source_name"] for x in items_data})
    digest.category_count = len(cat_stats)
    await db.flush()

    try:
        result = await call_llm_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3000,
            scene="weekly_digest",
        )

        # Validate LLM returned useful content — empty dict is a failure
        overview = result.get("overview", "")
        used_fallback = False
        if not overview or "raw_response" in result:
            logger.warning("Weekly digest LLM returned invalid content, using fallback: %s", str(result)[:200])
            result = build_digest_fallback(items_data, label=week_label)
            overview = result.get("overview", "")
            used_fallback = True

        digest.overview = overview
        # fallback 已自带 content_id（digest_fallback 从 item 直接构造）；
        # LLM 路径按 source_idx 回引匹配注入 content_id。注意：source_idx 对齐 prompt
        # 的前 25 条，但 title 兜底需搜索全量 items_data（LLM 可能选到非前 25 的素材，
        # 实测其 title 常接近原文，全量搜索命中率更高）。
        if used_fallback:
            apply_llm_result(digest, result)
        else:
            apply_llm_result_with_matching(digest, result, items_data)
        digest.status = "DONE"
        digest.updated_at = utc_now()
        await db.commit()
        logger.info("Weekly digest generated: %s (%s)", week_key, week_label)
        # 通知：周刊生成成功
        await push_digest_notification("success", "weekly_digest", "AI周刊生成完成", f"{week_label} 已生成")

        # webhook 卡片推送（失败不阻塞周报生成）
        try:
            from app.services.alerting import send_alert

            # 构造卡片内容：overview 摘要 + top 3 picks
            overview_text = (digest.overview or "")[:200]
            top_picks_raw = json.loads(digest.top_picks or "[]")
            top3_lines: list[str] = []
            for i, pick in enumerate(top_picks_raw[:3], start=1):
                title = pick.get("title") or f"选题 {i}"
                category = pick.get("category", "")
                cat_tag = f" `[{category}]`" if category else ""
                top3_lines.append(f"**{i}. {title}**{cat_tag}")

            card_content_parts = [overview_text]
            if top3_lines:
                card_content_parts.append("\n---\n**本周精选 Top 3：**\n" + "\n".join(top3_lines))

            card_content = "\n".join(card_content_parts)
            card_link = "/weekly"

            await send_alert(
                title=f"📚 AI 周刊 · {week_label}",
                message=f"周报生成完成：{week_label}",
                alert_key=f"weekly_digest:{week_key}",
                severity="info",
                event_type="weekly_digest",
                card={"content": card_content, "link": card_link},
            )
        except Exception:
            logger.warning("weekly_digest webhook push failed (non-fatal)", exc_info=True)
    except Exception as e:
        await commit_digest_error(digest, e, "周刊", week_key, db)

    return digest
