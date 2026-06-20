"""Today-picks business logic backed by DuckDB analytical reads."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import ContentItem
from app.services.duckdb_service import query_today_picks, query_topics
from app.services.scoring_engine import ScoreBreakdown, ScoringInput, score_items

logger = logging.getLogger(__name__)

TODAY_PICKS_THRESHOLD = 55
# OLTP fallback 拉取上限：避免一次拉到几万条无分析记录
_OLTP_FALLBACK_CANDIDATE_LIMIT = 200
# 与 SCORING_CONFIG["risk_threshold"] 对齐；这里硬编码避免循环 import
_OLTP_FALLBACK_RISK_THRESHOLD = 50.0


async def build_today_picks(
    db: AsyncSession,
    *,
    category: str | None = None,
    hours: int = 48,
    limit: int | None = None,
) -> dict:
    """Return today-picks payload through DuckDB, with OLTP fallback.

    首选 DuckDB（OLTP schema 通过 ATTACH 直接读，含 feedback_score 聚合、
    source_weight 加成、ignored 过滤）。

    若 DuckDB 不可用（扩展缺失、ATTACH 失败、host 无法解析等），降级到
    ``_build_today_picks_via_oltp``：走 SQLAlchemy 拉 ContentItem + analyses，
    输出与 DuckDB 路径**完全一致**的 row dict 结构，便于 scoring / payload
    构造代码复用。降级路径会少几个 DuckDB-only 字段（feedback_score=0、
    duplicate_of=None、source_weight 加成关闭），得分会偏低但**有数据**。
    """
    duckdb_exc: Exception | None = None
    try:
        rows = query_today_picks(
            hours=hours,
            category=category,
            limit=limit,
            # DuckDB supplies candidates; the unified scorer below is the only final gate.
            curation_threshold=0,
        )
    except Exception as exc:
        duckdb_exc = exc
        logger.warning(
            "today_picks DuckDB analytical layer unavailable, falling back to OLTP query: %s",
            exc,
            exc_info=True,
        )
        try:
            rows = await _build_today_picks_via_oltp(db, hours=hours, category=category, limit=limit)
        except Exception as oltp_exc:
            # OLTP 路径也挂了：记双错误，回退到空 payload（避免 5xx）
            logger.error(
                "today_picks OLTP fallback also failed: %s (original DuckDB error: %s)",
                oltp_exc,
                duckdb_exc,
                exc_info=True,
            )
            return _empty_payload()

    scored_rows = _score_rows(rows)
    if not scored_rows:
        return _empty_payload()

    response_items = [_row_to_content_payload(row, breakdown) for breakdown, row in scored_rows]
    try:
        topic_map = {topic["id"]: topic for topic in query_topics()}
    except Exception as exc:
        # topics 拉取失败：不阻塞主结果，只是不带话题关联
        logger.warning("today_picks query_topics failed, continuing without topics: %s", exc, exc_info=True)
        topic_map = {}

    return _dedupe_and_pack(
        response_items,
        topic_map,
        duplicates_hidden=sum(1 for row in rows if row.get("duplicate_of")),
        limit=limit,
    )


async def _build_today_picks_via_oltp(
    db: AsyncSession,
    *,
    hours: int,
    category: str | None,
    limit: int | None,
) -> list[dict]:
    """OLTP fallback：直接走 SQLAlchemy 拉 ContentItem + analyses，
    输出与 ``query_today_picks`` 一致的 row dict，便于 scoring 复用。

    简化点（vs DuckDB 路径）:
    - 无 ignored 过滤（数据量小时影响不大）
    - 无 feedback_score 聚合（=0）
    - 无 source_weight 加成（adjusted_curation_score = curation_score 原值）
    - 一次拉 _OLTP_FALLBACK_CANDIDATE_LIMIT 条，由统一 scorer 决定最终入选
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    fetch_limit = min(limit * 5, _OLTP_FALLBACK_CANDIDATE_LIMIT) if limit else _OLTP_FALLBACK_CANDIDATE_LIMIT

    stmt = (
        select(ContentItem)
        .options(
            selectinload(ContentItem.analyses),
            selectinload(ContentItem.source),
        )
        .where(ContentItem.crawled_at >= cutoff)
        .order_by(ContentItem.crawled_at.desc())
        .limit(fetch_limit)
    )
    if category:
        stmt = stmt.where(ContentItem.category == category)

    result = await db.execute(stmt)
    items = result.scalars().unique().all()

    rows: list[dict] = []
    for item in items:
        if not item.analyses:
            continue
        # analyses 关系已按 (created_at, id) 排序（model 端配置）
        latest = item.analyses[-1]
        if latest.curation_score is None:
            continue
        if latest.risk_score is not None and latest.risk_score > _OLTP_FALLBACK_RISK_THRESHOLD:
            continue

        source = item.source
        source_weight_db = source.weight if source else 3

        rows.append(
            {
                "id": item.id,
                "title": item.title or "",
                "url": item.url or "",
                "source_id": item.source_id,
                "source_name": source.name if source else None,
                "source_type": str(item.source_type) if item.source_type else None,
                "platform": None,
                "author": None,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "crawled_at": item.crawled_at.isoformat() if item.crawled_at else None,
                "content_hash": item.content_hash,
                "summary": item.summary,
                "raw_content": item.raw_content,
                "cover_url": item.cover_url,
                "category": item.category,
                "tags": item.tags,
                "language": item.language,
                "status": str(item.status) if item.status else "analyzed",
                "is_favorited": bool(item.is_favorited),
                "topic_id": item.topic_id,
                "duplicate_of": None,  # OLTP 不跑 dedup join
                "similarity_score": None,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "analysis_id": latest.id,
                "analysis_created_at": latest.created_at.isoformat(),
                "quality_score": latest.quality_score or 0,
                "hot_score": latest.hot_score or 0,
                "freshness_score": latest.freshness_score or 0,
                "creator_score": latest.creator_score or 0,
                "viral_score": latest.viral_score or 0,
                "risk_score": latest.risk_score or 0,
                "curation_score": latest.curation_score or 0,
                "info_density": latest.info_density or 0,
                "actionability": latest.actionability or 0,
                "recommended_reason": latest.recommended_reason,
                "recommendation": latest.recommendation,
                "ai_summary": latest.summary,
                "ai_tags": latest.tags,
                "enrichment_status": latest.enrichment_status,
                "enrichment": latest.enrichment,
                "analysis_source_weight": None,  # OLTP 不存这个字段
                "source_weight_db": source_weight_db,
                "feedback_score": 0,  # OLTP 不做 user_feedback 聚合
                "adjusted_curation_score": latest.curation_score or 0,  # 无加成
            }
        )
    return rows


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
