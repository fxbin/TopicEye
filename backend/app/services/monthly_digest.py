"""
Monthly Digest service — generate AI-powered monthly curated newsletter.
"""

from __future__ import annotations

import logging
from calendar import monthrange
from datetime import date, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.time import utc_now
from app.models.monthly_digest import MonthlyDigest
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
    fetch_analyzed_content_with_expanded_window,
)
from app.services.digest_fallback import build_digest_fallback
from app.services.llm import call_llm_json
from app.services.llm.prompts.digest import build_monthly_digest_prompt

logger = logging.getLogger(__name__)


def _get_month_range(reference_date: date | None = None) -> tuple[str, str, str, str]:
    """Return (month_key, month_label, month_start_iso, month_end_iso)."""
    current = reference_date or date.today()
    month_key = f"{current.year}-{current.month:02d}"
    month_label = f"{current.year}年{current.month}月"
    month_start = date(current.year, current.month, 1)
    month_end = date(current.year, current.month, monthrange(current.year, current.month)[1])
    return month_key, month_label, month_start.isoformat(), month_end.isoformat()


def _previous_month(reference_date: date | None = None) -> date:
    current = reference_date or date.today()
    if current.month == 1:
        return date(current.year - 1, 12, 1)
    return date(current.year, current.month - 1, 1)


def _is_active_generating(digest: MonthlyDigest, now: datetime) -> bool:
    return is_active_generating(digest, now)


async def generate_monthly_digest(
    db: AsyncSession,
    reference_date: date | None = None,
    use_previous_month: bool = True,
) -> MonthlyDigest:
    """Generate or regenerate a monthly digest.

    By default, generates the previous full month. API callers can pass
    use_previous_month=False to regenerate a specific month key.
    """
    target_date = _previous_month(reference_date) if use_previous_month else (reference_date or date.today())
    month_key, month_label, month_start, month_end = _get_month_range(target_date)
    now = utc_now()

    async def _claim_generation() -> tuple[MonthlyDigest, bool]:
        existing_stmt = select(MonthlyDigest).where(MonthlyDigest.month_key == month_key).with_for_update()

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
                    existing_stmt.with_for_update()
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

    digest, claimed = await _claim_generation()
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
    prompt = build_monthly_digest_prompt(
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
        used_fallback = False
        if not overview or "raw_response" in result:
            logger.warning("Monthly digest LLM returned invalid content, using fallback: %s", str(result)[:200])
            result = build_digest_fallback(items_data, label=month_label)
            overview = result.get("overview", "")
            used_fallback = True

        digest.overview = overview
        # fallback 已自带 content_id；LLM 路径按 source_idx 回引匹配注入。
        # title 兜底搜索全量 items_data（LLM 可能选到非前 40 的素材）。
        if used_fallback:
            apply_llm_result(digest, result)
        else:
            apply_llm_result_with_matching(digest, result, items_data)
        digest.status = "DONE"
        digest.updated_at = utc_now()
        await db.commit()
        logger.info("Monthly digest generated: %s (%s)", month_key, month_label)
        await push_digest_notification("success", "monthly_digest", "AI月刊生成完成", f"{month_label} 已生成")
    except Exception as exc:
        await commit_digest_error(digest, exc, "月刊", month_key, db)

    return digest
