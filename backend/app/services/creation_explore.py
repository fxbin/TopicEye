"""
Explore-mode creation plan service — three-step scaffolding flow.

This module implements the "衰减式脚手架" architecture from the roundtable
discussion (Round 4-5). It coexists with the existing fast-mode
``generate_creation_plan`` — fast mode is a one-shot call, explore mode is
a three-step conversation:

  1. explore  — assumption challenge + direction generation  (AI: 100%)
  2. focus    — Socratic questioning, user redirects freely     (AI: 50%)
  3. converge — structured plan output with confidence labels   (AI: 20%)

Used by:
    - app.api.v1.creation  (POST /creation/explore|focus|converge)
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.services.llm import call_llm_json
from app.services.llm.prompts.creation import (
    CONVERGE_PROMPT,
    EXPLORE_PROMPT,
    FOCUS_PROMPT,
    PLATFORM_PROMPTS,
)

logger = logging.getLogger(__name__)


# ── shared helpers ──────────────────────────────────────────────────


async def _fetch_content_and_analysis(
    db: AsyncSession,
    content_id: int,
) -> tuple[ContentItem, AiAnalysis] | None:
    """Fetch the content item and its latest analysis."""
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
    result = await db.execute(
        select(ContentItem, AiAnalysis)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(ContentItem.id == content_id)
    )
    row = result.first()
    if not row:
        return None
    return row


def _build_source_info(analysis: AiAnalysis) -> dict[str, str]:
    """Extract analysis fields into a flat dict for prompt interpolation."""
    tags = analysis.tags
    if not isinstance(tags, list):
        tags = json.loads(tags or "[]")

    return {
        "summary": analysis.summary or "",
        "key_points": "; ".join(analysis.key_points or []),
        "tags": ", ".join(tags),
        "creator_angles": "; ".join(analysis.creator_angles or []),
    }


# ── Step 1: Explore (assumption challenge + direction generation) ──


async def generate_explore_directions(
    db: AsyncSession,
    content_id: int,
) -> dict[str, Any]:
    """
    Explore phase: AI finds 3 domain assumptions, challenges them,
    and generates creative directions.

    Returns:
        {"assumptions": [...], "_meta": {"content_id": ..., "phase": "explore"}}
        or {"error": "..."}
    """
    fetched = await _fetch_content_and_analysis(db, content_id)
    if not fetched:
        return {"error": "内容不存在或未分析"}

    content, analysis = fetched
    info = _build_source_info(analysis)

    user_msg = EXPLORE_PROMPT.format(
        title=content.title,
        source_name=content.source_name or "",
        summary=info["summary"],
        key_points=info["key_points"],
        tags=info["tags"],
        creator_angles=info["creator_angles"],
    )

    messages = [
        {"role": "user", "content": user_msg},
    ]

    try:
        result = await asyncio.wait_for(
            call_llm_json(messages, scene="creation_explore"),
            timeout=settings.CREATION_PLAN_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Explore phase timed out for content %s", content_id)
        return {"error": f"探索期超时（>{settings.CREATION_PLAN_TIMEOUT_SECONDS}s），请重试"}
    except Exception as e:
        logger.exception("Explore phase failed for content %s", content_id)
        return {"error": str(e)}

    if not isinstance(result, dict) or "assumptions" not in result:
        return {"error": "探索期返回格式异常"}

    result["_meta"] = {"content_id": content_id, "phase": "explore"}
    return result


# ── Step 2: Focus (Socratic questioning) ──────────────────────────


async def generate_focus_questions(
    db: AsyncSession,
    content_id: int,
    selected_direction: str,
    unique_value: str,
    pitfall: str,
    focus_round: int = 1,
    previous_qa: list[dict] | None = None,
    user_redirect: str | None = None,
) -> dict[str, Any]:
    """
    Focus phase: AI asks one Socratic question per round.
    User can redirect — if *user_redirect* is provided, AI must switch dimension.

    Returns:
        {"question": "...", "dimension": "...", "round": N,
         "can_converge": bool, "reason": "...", "_meta": {...}}
    """
    fetched = await _fetch_content_and_analysis(db, content_id)
    if not fetched:
        return {"error": "内容不存在或未分析"}

    content, analysis = fetched
    info = _build_source_info(analysis)

    user_msg = FOCUS_PROMPT.format(
        selected_direction=selected_direction,
        unique_value=unique_value,
        pitfall=pitfall,
        summary=info["summary"],
        key_points=info["key_points"],
    )

    # Build conversation context from previous rounds
    messages = [{"role": "user", "content": user_msg}]
    if previous_qa:
        for qa in previous_qa:
            messages.append({"role": "assistant", "content": json.dumps(qa, ensure_ascii=False)})
            if qa.get("user_answer"):
                messages.append({"role": "user", "content": qa["user_answer"]})

    if user_redirect:
        messages.append({
            "role": "user",
            "content": f"方向不对，我要走另一条路。{user_redirect}",
        })

    messages.append({
        "role": "user",
        "content": f"这是第 {focus_round} 轮追问，请输出本轮问题。",
    })

    try:
        result = await asyncio.wait_for(
            call_llm_json(messages, scene="creation_focus"),
            timeout=settings.CREATION_PLAN_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Focus phase timed out for content %s round %s", content_id, focus_round)
        return {"error": f"聚焦期超时（>{settings.CREATION_PLAN_TIMEOUT_SECONDS}s），请重试"}
    except Exception as e:
        logger.exception("Focus phase failed for content %s round %s", content_id, focus_round)
        return {"error": str(e)}

    if not isinstance(result, dict) or "question" not in result:
        return {"error": "聚焦期返回格式异常"}

    result["round"] = focus_round
    result["_meta"] = {
        "content_id": content_id,
        "phase": "focus",
        "round": focus_round,
    }
    return result


# ── Step 3: Converge (structured plan output) ──────────────────────


async def generate_converge_plan(
    db: AsyncSession,
    content_id: int,
    platform: str,
    selected_direction: str,
    focus_answers: list[dict],
    user_id: int | None = None,
) -> dict[str, Any]:
    """
    Converge phase: AI outputs a structured creation plan with
    confidence annotations and assumption verification status.

    Returns the final plan dict (persisted to creation_plans table).
    """
    fetched = await _fetch_content_and_analysis(db, content_id)
    if not fetched:
        return {"error": "内容不存在或未分析"}

    content, analysis = fetched
    info = _build_source_info(analysis)

    platform_config = PLATFORM_PROMPTS.get(platform)
    if not platform_config:
        return {"error": f"不支持的平台: {platform}"}

    # Format focus answers into a readable string
    focus_text_parts = []
    for qa in focus_answers:
        q = qa.get("question", "")
        a = qa.get("user_answer", "")
        focus_text_parts.append(f"问：{q}\n答：{a}")
    focus_answers_text = "\n\n".join(focus_text_parts) if focus_text_parts else "无追问记录"

    user_msg = CONVERGE_PROMPT.format(
        platform_name=platform_config["name"],
        selected_direction=selected_direction,
        focus_answers=focus_answers_text,
        title=content.title,
        summary=info["summary"],
        key_points=info["key_points"],
    )

    messages = [
        {"role": "user", "content": user_msg},
    ]

    try:
        plan = await asyncio.wait_for(
            call_llm_json(messages, scene="creation_converge"),
            timeout=settings.CREATION_PLAN_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.warning("Converge phase timed out for content %s", content_id)
        return {"error": f"收敛期超时（>{settings.CREATION_PLAN_TIMEOUT_SECONDS}s），请重试"}
    except Exception as e:
        logger.exception("Converge phase failed for content %s", content_id)
        return {"error": str(e)}

    if not isinstance(plan, dict) or "titles" not in plan:
        return {"error": "收敛期返回格式异常，缺少标题"}

    # Validate basic structure
    titles = [t for t in plan.get("titles", []) if isinstance(t, str) and t.strip()]
    if not titles:
        return {"error": "收敛期未返回可用标题"}
    plan["titles"] = titles

    plan["_meta"] = {
        "content_id": content_id,
        "platform": platform,
        "platform_name": platform_config["name"],
        "mode": "explore",
        "phase": "converge",
    }

    # Persist to creation_plans table (same as fast mode)
    await _persist_explore_plan(
        db,
        user_id=user_id,
        content_id=content_id,
        content_title=content.title,
        platform=platform,
        platform_name=platform_config["name"],
        plan=plan,
    )

    return plan


async def _persist_explore_plan(
    db: AsyncSession,
    *,
    user_id: int | None,
    content_id: int,
    content_title: str,
    platform: str,
    platform_name: str,
    plan: dict,
) -> None:
    """Persist the explore-mode plan to creation_plans table."""
    from app.models.creation import CreationPlan

    record = CreationPlan(
        user_id=user_id,
        content_id=content_id,
        platform=platform,
        platform_name=platform_name,
        content_title_snapshot=content_title[:500],
        plan=plan,
        error=None,
    )
    db.add(record)
    try:
        await db.flush()
    except Exception:
        logger.warning("Persist explore plan failed (non-fatal)", exc_info=True)
        await db.rollback()
