"""
Round-2 AI Enrichment service.

Takes a content item that has completed Round-1 analysis (summary, tags, curation_score),
finds related items from the same topic group, and generates richer context for creators:

  - background_knowledge: Why this happened, historical context
  - related_angles: Different takes from related stories (same topic, different angles)
  - why_matters: Why this matters to content creators specifically
  - creator_tips: Specific angles or hooks a creator can use

Triggered:
  - On-demand: GET /api/v1/contents/{id}/enrich
  - Batch: scheduler nightly for top-N curated items (curation_score >= 70)
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.database import async_session
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.topic import TopicGroup
from app.repositories.analysis_queries import (
    latest_analysis_id_for_content_id,
    latest_analysis_id_subquery,
)
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.llm import call_llm_json
from app.services.llm.prompts.enrichment import ENRICHMENT_PROMPT, SYSTEM_PROMPT
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)


def _normalize_enrichment_concurrency(value: int | None = None) -> int:
    try:
        parsed = int(value if value is not None else settings.ENRICHMENT_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 10))


def _session_factory_from_session(db: AsyncSession) -> Callable[[], Any]:
    bind = getattr(db, "bind", None)
    if bind is None:
        return async_session
    return async_sessionmaker(bind, expire_on_commit=False)


async def _build_related_context(items: list[dict]) -> str:
    """Format related items for the prompt."""
    if not items:
        return "（无关联内容）"
    lines = []
    for item in items[:5]:  # cap at 5 related items
        lines.append(
            f"- [{item['id']}] {item['title']}" + (f" | 摘要: {item['summary'][:80]}" if item.get("summary") else "")
        )
    return "\n".join(lines)


async def enrich_content(
    content_id: int,
    db: AsyncSession,
) -> dict[str, Any]:
    """
    Run Round-2 enrichment on a single content item.

    Returns the enrichment dict to store in `ai_analyses.enrichment`.
    """
    # Load content + analysis + topic
    latest_analysis_id = latest_analysis_id_for_content_id(content_id)
    result = await db.execute(
        select(AiAnalysis, ContentItem, TopicGroup)
        .join(ContentItem, AiAnalysis.content_id == ContentItem.id)
        .outerjoin(TopicGroup, ContentItem.topic_id == TopicGroup.id)
        .where(AiAnalysis.id == latest_analysis_id)
    )
    row = result.first()
    if not row:
        raise ValueError(f"No analysis found for content_id={content_id}")

    analysis, content, _topic = row[0], row[1], row[2]

    # Fetch related items from same topic group
    related_items: list[dict] = []
    if content.topic_id:
        related_latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
        rel_result = await db.execute(
            select(ContentItem, AiAnalysis)
            .join(AiAnalysis, AiAnalysis.id == related_latest_analysis_id)
            .where(
                and_(
                    ContentItem.topic_id == content.topic_id,
                    ContentItem.id != content_id,
                    AiAnalysis.summary.isnot(None),
                )
            )
            .order_by(AiAnalysis.curation_score.desc())
            .limit(5)
        )
        for rel_content, rel_analysis in rel_result.all():
            related_items.append(
                {
                    "id": rel_content.id,
                    "title": rel_content.title,
                    "summary": rel_analysis.summary or "",
                }
            )

    # Build tags string
    tags_str = ""
    if analysis.tags:
        try:
            tags = analysis.tags if isinstance(analysis.tags, list) else json.loads(analysis.tags)
            tags_str = ", ".join(str(t) for t in tags[:5])
        except Exception:
            tags_str = str(analysis.tags)

    related_text = await _build_related_context(related_items)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": ENRICHMENT_PROMPT.format(
                title=sanitize_prompt_input(content.title, max_chars=500),
                summary=sanitize_prompt_input(analysis.summary or "无", max_chars=500),
                tags=sanitize_prompt_input(tags_str or "无", max_chars=200),
                curation_score=analysis.curation_score or 0,
                source_name=sanitize_prompt_input(content.source_name or "未知", max_chars=200),
                related_items=sanitize_prompt_input(related_text, max_chars=2000),
            ),
        },
    ]

    try:
        result_data = await call_llm_json(messages, temperature=0.2, max_tokens=1200, scene="content_enrichment")

        # Validate structure
        enrichment = {
            "background_knowledge": str(result_data.get("background_knowledge", ""))[:200],
            "why_matters": str(result_data.get("why_matters", ""))[:200],
            "related_angles": result_data.get("related_angles", [])[:3],
            "creator_tips": result_data.get("creator_tips", [])[:3],
            "story_hooks": result_data.get("story_hooks", [])[:3],
            "related_items": related_items,
        }

        logger.info(
            "Enrichment done for content_id=%d: %s", content_id, enrichment.get("background_knowledge", "")[:50]
        )
        return enrichment

    except Exception as exc:
        logger.warning("Enrichment failed for content_id=%d: %s", content_id, exc)
        raise


async def enrich_batch(
    content_ids: list[int],
    db: AsyncSession,
    *,
    concurrency: int | None = None,
    session_factory: Callable[[], Any] | None = None,
) -> list[dict[str, Any]]:
    """Run enrichment on multiple content items with bounded concurrency."""
    if not content_ids:
        return []

    limit = _normalize_enrichment_concurrency(concurrency)
    semaphore = asyncio.Semaphore(limit)
    factory = session_factory or _session_factory_from_session(db)

    async def _run_one(cid: int) -> dict[str, Any]:
        async with semaphore, factory() as item_db:
            return await _enrich_one_claimed(cid, item_db)

    return await asyncio.gather(*(_run_one(cid) for cid in content_ids))


async def _enrich_one_claimed(cid: int, db: AsyncSession) -> dict[str, Any]:
    try:
        data = await enrich_content(cid, db)
        result = await db.execute(select(AiAnalysis).where(AiAnalysis.id == latest_analysis_id_for_content_id(cid)))
        record = result.scalar_one_or_none()
        if record:
            record.enrichment = data
            record.enrichment_status = "completed"
        await db.commit()
        invalidate_content_read_caches()
        return {"content_id": cid, "status": "completed", "data": data}
    except Exception as e:
        logger.error("Enrich batch item %d failed: %s", cid, e)
        await db.rollback()
        try:
            result = await db.execute(select(AiAnalysis).where(AiAnalysis.id == latest_analysis_id_for_content_id(cid)))
            record = result.scalar_one_or_none()
            if record:
                record.enrichment_status = "error"
            await db.commit()
            invalidate_content_read_caches()
        except Exception as status_error:
            await db.rollback()
            logger.warning("Failed to mark enrichment error for content_id=%d: %s", cid, status_error)
        return {"content_id": cid, "status": "error", "error": str(e)}
