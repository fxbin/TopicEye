"""
Monthly Digest service — generate AI-powered monthly curated newsletter.
"""

from __future__ import annotations

import json
import logging
from calendar import monthrange
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_profile
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.monthly_digest import MonthlyDigest
from app.services.digest_fallback import build_digest_fallback
from app.services.digest_context import (
    build_category_stats,
    build_category_text,
    build_items_text,
    fetch_analyzed_content_with_expanded_window,
)
from app.services.llm import call_llm_json
from app.services.llm.prompts.monthly_digest import MONTHLY_DIGEST_PROMPT

logger = logging.getLogger(__name__)
DIGEST_GENERATING_STALE_AFTER = timedelta(minutes=10)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _get_month_range(reference_date: Optional[date] = None) -> tuple[str, str, str, str]:
    """Return (month_key, month_label, month_start_iso, month_end_iso)."""
    current = reference_date or date.today()
    month_key = f"{current.year}-{current.month:02d}"
    month_label = f"{current.year}年{current.month}月"
    month_start = date(current.year, current.month, 1)
    month_end = date(current.year, current.month, monthrange(current.year, current.month)[1])
    return month_key, month_label, month_start.isoformat(), month_end.isoformat()


def _previous_month(reference_date: Optional[date] = None) -> date:
    current = reference_date or date.today()
    if current.month == 1:
        return date(current.year - 1, 12, 1)
    return date(current.year, current.month - 1, 1)


def _is_active_generating(digest: MonthlyDigest, now: datetime) -> bool:
    if digest.status != "GENERATING":
        return False
    generated_at = digest.updated_at or digest.created_at or now
    return now - generated_at < DIGEST_GENERATING_STALE_AFTER


async def generate_monthly_digest(
    db: AsyncSession,
    reference_date: Optional[date] = None,
    use_previous_month: bool = True,
) -> MonthlyDigest:
    """Generate or regenerate a monthly digest.

    By default, generates the previous full month. API callers can pass
    use_previous_month=False to regenerate a specific month key.
    """
    target_date = _previous_month(reference_date) if use_previous_month else (reference_date or date.today())
    month_key, month_label, month_start, month_end = _get_month_range(target_date)
    now = _utc_now()

    async def _claim_generation() -> tuple[MonthlyDigest, bool]:
        if database_profile.is_sqlite:
            await begin_immediate_for_sqlite(db)

        existing_stmt = select(MonthlyDigest).where(MonthlyDigest.month_key == month_key)
        if database_profile.is_postgresql:
            existing_stmt = existing_stmt.with_for_update()

        existing = await db.execute(existing_stmt)
        digest = existing.scalar_one_or_none()
        if digest and digest.status == "DONE":
            return digest, False
        if digest and _is_active_generating(digest, now):
            return digest, False

        if not digest:
            digest = MonthlyDigest(
                month_key=month_key,
                month_label=month_label,
                month_start=month_start,
                month_end=month_end,
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
                if _is_active_generating(digest, _utc_now()):
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

    items_data = await fetch_analyzed_content_with_expanded_window(
        db,
        month_start,
        month_end,
        expanded_days=30,
    )

    if not items_data:
        digest.status = "ERROR"
        digest.overview = "本月暂无分析数据，请先同步信源并等待 AI 分析完成。"
        await db.commit()
        return digest

    category_stats = build_category_stats(items_data)
    prompt = MONTHLY_DIGEST_PROMPT.format(
        month_label=month_label,
        items_text=build_items_text(items_data, limit=40),
        category_text=build_category_text(category_stats),
    )

    content_stats = {
        "content_count": len(items_data),
        "analyzed_count": len(items_data),
        "source_count": len({x["source_name"] for x in items_data}),
        "category_count": len(category_stats),
    }

    for key, value in content_stats.items():
        setattr(digest, key, value)
    await db.flush()

    try:
        result = await call_llm_json(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=3600,
            scene="monthly_digest",
        )

        overview = result.get("overview", "")
        if not overview or "raw_response" in result:
            logger.warning("Monthly digest LLM returned invalid content, using fallback: %s", str(result)[:200])
            result = build_digest_fallback(items_data, label=month_label)
            overview = result.get("overview", "")

        digest.overview = overview
        digest.takeaway = result.get("takeaway", "")
        digest.keywords = json.dumps(result.get("keywords", []), ensure_ascii=False)
        digest.trends = json.dumps(result.get("trends", []), ensure_ascii=False)
        digest.top_picks = json.dumps(result.get("top_picks", []), ensure_ascii=False)
        digest.category_summary = json.dumps(result.get("category_summary", {}), ensure_ascii=False)
        digest.platform_tips = json.dumps(result.get("platform_tips", {}), ensure_ascii=False)
        digest.topic_clusters = json.dumps(result.get("topic_clusters", []), ensure_ascii=False)
        digest.action_items = json.dumps(result.get("action_items", []), ensure_ascii=False)
        digest.status = "DONE"
        digest.updated_at = _utc_now()
        await db.commit()
        logger.info("Monthly digest generated: %s (%s)", month_key, month_label)
        try:
            from app.services.notification_service import push_notification

            await push_notification("success", "monthly_digest", "AI月刊生成完成", f"{month_label} 已生成")
        except Exception:
            pass
    except Exception as exc:
        digest.status = "ERROR"
        digest.overview = f"生成失败: {str(exc)[:200]}"
        await db.commit()
        logger.error("Monthly digest generation failed for %s: %s", month_key, exc)
        try:
            from app.services.notification_service import push_notification

            await push_notification("error", "monthly_digest", "AI月刊生成失败", str(exc)[:200])
        except Exception:
            pass

    return digest
