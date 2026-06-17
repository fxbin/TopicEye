"""Today-picks business logic backed by DuckDB analytical reads."""

from __future__ import annotations

from datetime import datetime, timezone, UTC
import json
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.duckdb_service import query_today_picks, query_topics
from app.services.scoring_engine import ScoreBreakdown, ScoringInput, score_items

TODAY_PICKS_THRESHOLD = 55


async def build_today_picks(
    db: AsyncSession,
    *,
    category: str | None = None,
    hours: int = 48,
    limit: int | None = None,
) -> dict:
    """Return today-picks payload through the fixed DuckDB analytical layer."""
    _ = db
    rows = query_today_picks(
        hours=hours,
        category=category,
        limit=limit,
        # DuckDB supplies candidates; the unified scorer below is the only final gate.
        curation_threshold=0,
    )
    scored_rows = _score_rows(rows)
    if not scored_rows:
        return _empty_payload()

    response_items = [_row_to_content_payload(row, breakdown) for breakdown, row in scored_rows]
    topic_map = {topic["id"]: topic for topic in query_topics()}
    return _dedupe_and_pack(
        response_items,
        topic_map,
        duplicates_hidden=sum(1 for row in rows if row.get("duplicate_of")),
        limit=limit,
    )


def _empty_payload() -> dict:
    return {
        "items": [],
        "total": 0,
        "duplicates_hidden": 0,
        "topics": [],
        "page": 1,
        "page_size": 0,
    }


def _score_rows(rows: list[dict]) -> list[tuple[ScoreBreakdown, dict]]:
    input_rows: list[tuple[ScoringInput, dict]] = [
        (_row_to_scoring_input(row), row) for row in rows if row.get("duplicate_of") is None
    ]
    row_map = {item.content_id: row for item, row in input_rows}
    scored = score_items([item for item, _row in input_rows])
    return [
        (breakdown, row_map[item.content_id])
        for breakdown, item in scored
        if breakdown.selected and breakdown.final_score >= TODAY_PICKS_THRESHOLD
    ]


def _row_to_scoring_input(row: dict) -> ScoringInput:
    return ScoringInput(
        content_id=row["id"],
        title=row.get("title") or "",
        category=row.get("category"),
        source_id=row.get("source_id"),
        source_name=row.get("source_name"),
        published_at=row.get("published_at"),
        crawled_at=row.get("crawled_at"),
        curation_score=row.get("curation_score") or 0,
        info_density=row.get("info_density") or 50,
        actionability=row.get("actionability") or 50,
        source_weight=row.get("analysis_source_weight") or row.get("source_weight") or 50,
        creator_score=row.get("creator_score") or 0,
        viral_score=row.get("viral_score") or 0,
        freshness_score=row.get("freshness_score") or 0,
        quality_score=row.get("quality_score") or 0,
        hot_score=row.get("hot_score") or 0,
        risk_score=row.get("risk_score") or 0,
        source_weight_db=row.get("source_weight_db") or row.get("source_weight") or 3,
        feedback_score=row.get("feedback_score") or 0,
    )


def _row_to_content_payload(row: dict, breakdown: ScoreBreakdown) -> dict:
    content_tags = _decode_json_value(row.get("tags"))
    analysis_tags = _decode_json_value(row.get("ai_tags")) or content_tags
    enrichment = _decode_json_value(row.get("enrichment"))
    score_breakdown = breakdown.to_dict()
    analysis = {
        "id": row.get("analysis_id") or 0,
        "content_id": row["id"],
        "quality_score": row.get("quality_score") or 0,
        "hot_score": row.get("hot_score") or 0,
        "freshness_score": row.get("freshness_score") or 0,
        "creator_score": row.get("creator_score") or 0,
        "viral_score": row.get("viral_score") or 0,
        "risk_score": row.get("risk_score") or 0,
        "platform_fit": None,
        "recommended_reason": row.get("recommended_reason"),
        "summary": row.get("ai_summary"),
        "key_points": None,
        "audience_emotion": None,
        "creator_angles": None,
        "title_suggestions": None,
        "outline_suggestions": None,
        "xiaohongshu_plan": None,
        "short_video_plan": None,
        "risk_notes": None,
        "curation_score": row.get("curation_score") or 0,
        "tags": analysis_tags,
        "recommendation": row.get("recommendation"),
        "info_density": row.get("info_density") or 0,
        "actionability": row.get("actionability") or 0,
        "source_weight": row.get("analysis_source_weight") or row.get("source_weight") or 0,
        "enrichment_status": row.get("enrichment_status") or "pending",
        "enrichment": enrichment,
        "created_at": row.get("analysis_created_at") or row.get("created_at") or datetime.now(UTC).isoformat(),
        "adjusted_curation_score": score_breakdown["final_score"],
        "score_breakdown": score_breakdown,
    }
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "source_id": row.get("source_id"),
        "source_name": row.get("source_name"),
        "source_type": row.get("source_type"),
        "platform": row.get("platform"),
        "author": row.get("author"),
        "published_at": row.get("published_at"),
        "crawled_at": row.get("crawled_at"),
        "content_hash": row.get("content_hash"),
        "summary": row.get("summary"),
        "raw_content": row.get("raw_content"),
        "cover_url": row.get("cover_url"),
        "category": row.get("category"),
        "tags": content_tags,
        "language": row.get("language"),
        "status": row.get("status") or "analyzed",
        "is_favorited": bool(row.get("is_favorited")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "topic_id": row.get("topic_id"),
        "duplicate_of": row.get("duplicate_of"),
        "similarity_score": row.get("similarity_score"),
        "analysis": analysis,
        "analyses": [analysis],
    }


def _decode_json_value(value):
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped == "null":
        return None
    if stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _dedupe_and_pack(
    items: list[dict],
    topic_map: dict,
    *,
    duplicates_hidden: int = 0,
    limit: int | None = None,
) -> dict:
    deduped = items
    total = len(deduped)
    if limit:
        deduped = deduped[:limit]
    topic_ids = {item.get("topic_id") for item in deduped if item.get("topic_id")}
    visible_topics = [topic for topic in topic_map.values() if topic["id"] in topic_ids]
    return {
        "items": deduped,
        "total": total,
        "duplicates_hidden": duplicates_hidden,
        "topics": visible_topics,
        "page": 1,
        "page_size": len(deduped),
    }
