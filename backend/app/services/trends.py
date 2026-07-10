"""
Trend snapshot service — computes daily/periodic aggregates.

Called by the scheduler after clustering. Produces TopicTrend rows
that the frontend queries for trend charts.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy import select, func, text, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.trend import TopicTrend
from app.models.topic import TopicGroup
from app.models.content import ContentItem
from app.models.analysis import AiAnalysis
from app.models.source import Source
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import ScoringInput, score_items

logger = logging.getLogger(__name__)


async def snapshot_daily_trends(db: AsyncSession, target_date: date | None = None) -> dict:
    """
    Compute and persist daily trend snapshots for topics and keywords.

    Returns {"topics": N, "keywords": N, "date": "YYYY-MM-DD"}.
    """
    if target_date is None:
        target_date = date.today()

    # ── 1. Delete existing snapshots for this date ──────────────────
    # 传 date 对象而非 isoformat 字符串：asyncpg 对 DATE 列严格校验，
    # 拒绝 str→date（SQLite 宽松接受，但 PG 会抛 'str' has no attribute 'toordinal'）
    await db.execute(
        text("DELETE FROM topic_trends WHERE snapshot_date = :d"),
        {"d": target_date},
    )

    # ── 2. Topic-level trends ───────────────────────────────────────
    # Get content items grouped by topic_id for the target date
    start_dt = datetime.combine(target_date, datetime.min.time())
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time())
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)

    topic_rows = await db.execute(
        select(
            ContentItem.topic_id,
            ContentItem.id,
            ContentItem.title,
            ContentItem.url,
            ContentItem.category,
            ContentItem.source_id,
            ContentItem.source_name,
            ContentItem.published_at,
            ContentItem.crawled_at,
            AiAnalysis.curation_score,
            AiAnalysis.info_density,
            AiAnalysis.actionability,
            AiAnalysis.source_weight.label("analysis_source_weight"),
            AiAnalysis.creator_score,
            AiAnalysis.viral_score,
            AiAnalysis.freshness_score,
            AiAnalysis.quality_score,
            AiAnalysis.hot_score,
            AiAnalysis.risk_score,
            Source.weight.label("source_weight_db"),
        )
        .select_from(ContentItem)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .outerjoin(Source, Source.id == ContentItem.source_id)
        .where(
            and_(
                ContentItem.topic_id.isnot(None),
                ContentItem.duplicate_of.is_(None),
                ContentItem.created_at >= start_dt,
                ContentItem.created_at < end_dt,
            )
        )
    )

    topic_items: dict[int, list] = {}
    content_ids: list[int] = []
    for row in topic_rows:
        topic_items.setdefault(row.topic_id, []).append(row)
        content_ids.append(row.id)

    feedback_scores = await get_feedback_scores(db, content_ids)

    topic_count = 0
    for topic_id, rows in topic_items.items():
        # Get topic name
        tg = await db.get(TopicGroup, topic_id)
        topic_name = tg.name if tg else f"Topic-{topic_id}"

        row_map = {row.id: row for row in rows}
        scored_items = score_items([_trend_row_to_scoring_input(row, feedback_scores.get(row.id, 0)) for row in rows])
        final_scores = [breakdown.final_score for breakdown, _item in scored_items]
        top_items = [
            {
                "title": row_map[item.content_id].title,
                "url": row_map[item.content_id].url,
                "score": round(breakdown.final_score or 0, 1),
            }
            for breakdown, item in scored_items[:3]
        ]

        snap = TopicTrend(
            snapshot_date=target_date,
            topic_id=topic_id,
            topic_name=topic_name,
            content_count=len(rows),
            avg_score=round(sum(final_scores) / len(final_scores), 1) if final_scores else 0,
            max_score=round(max(final_scores), 1) if final_scores else 0,
            pick_count=sum(1 for breakdown, _item in scored_items if breakdown.selected),
            top_items=top_items,
        )
        db.add(snap)
        topic_count += 1

    # ── 3. Keyword-level trends ─────────────────────────────────────
    # Extract from tags JSON, count frequency
    keyword_rows = await db.execute(
        select(AiAnalysis.tags)
        .select_from(ContentItem)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(
            and_(
                AiAnalysis.tags.isnot(None),
                ContentItem.duplicate_of.is_(None),
                ContentItem.created_at >= start_dt,
                ContentItem.created_at < end_dt,
            )
        )
    )

    keyword_stats: dict[str, list[float]] = {}
    for (tags_json,) in keyword_rows:
        if not tags_json:
            continue
        tags_list = tags_json if isinstance(tags_json, list) else json.loads(tags_json)
        for tag in tags_list:
            tag = tag.strip()
            if tag:
                keyword_stats.setdefault(tag, []).append(0)  # just counting

    keyword_count = 0
    for kw, occurrences in sorted(keyword_stats.items(), key=lambda x: len(x[1]), reverse=True)[:50]:  # top 50 keywords
        snap = TopicTrend(
            snapshot_date=target_date,
            keyword=kw,
            content_count=len(occurrences),
            avg_score=0,
            max_score=0,
            pick_count=0,
        )
        db.add(snap)
        keyword_count += 1

    await db.flush()
    logger.info(
        "Trend snapshot for %s: %d topics, %d keywords",
        target_date,
        topic_count,
        keyword_count,
    )

    return {"topics": topic_count, "keywords": keyword_count, "date": target_date.isoformat()}


def _trend_row_to_scoring_input(row, feedback_score: float = 0) -> ScoringInput:
    """Convert a trend snapshot candidate row into the unified scorer input."""
    return ScoringInput(
        content_id=row.id,
        title=row.title or "",
        category=row.category,
        source_id=row.source_id,
        source_name=row.source_name,
        published_at=row.published_at,
        crawled_at=row.crawled_at,
        curation_score=row.curation_score or 0,
        info_density=row.info_density or 50,
        actionability=row.actionability or 50,
        source_weight=row.analysis_source_weight or 50,
        creator_score=row.creator_score or 0,
        viral_score=row.viral_score or 0,
        freshness_score=row.freshness_score or 0,
        quality_score=row.quality_score or 0,
        hot_score=row.hot_score or 0,
        risk_score=row.risk_score or 0,
        source_weight_db=row.source_weight_db or 3,
        feedback_score=feedback_score,
    )


async def get_topic_trends(db: AsyncSession, days: int = 7) -> list[dict]:
    """Get topic trend data for the last N days."""
    cutoff = date.today() - timedelta(days=days)

    rows = await db.execute(
        select(TopicTrend)
        .where(
            and_(
                TopicTrend.topic_id.isnot(None),
                TopicTrend.snapshot_date >= cutoff,
            )
        )
        .order_by(TopicTrend.snapshot_date, TopicTrend.topic_id)
    )
    trends = rows.scalars().all()
    return [
        {
            "date": t.snapshot_date.isoformat(),
            "topic_id": t.topic_id,
            "topic_name": t.topic_name,
            "content_count": t.content_count,
            "avg_score": t.avg_score,
            "max_score": t.max_score,
            "pick_count": t.pick_count,
            "top_items": t.top_items,
        }
        for t in trends
    ]


async def get_keyword_cloud(db: AsyncSession, days: int = 7, limit: int = 50) -> list[dict]:
    """Get keyword frequency for word cloud, aggregated over N days."""
    cutoff = date.today() - timedelta(days=days)

    rows = await db.execute(
        select(
            TopicTrend.keyword,
            func.sum(TopicTrend.content_count).label("total"),
        )
        .where(
            and_(
                TopicTrend.keyword.isnot(None),
                TopicTrend.snapshot_date >= cutoff,
            )
        )
        .group_by(TopicTrend.keyword)
        .order_by(func.sum(TopicTrend.content_count).desc())
        .limit(limit)
    )

    return [{"keyword": r.keyword, "count": int(r.total)} for r in rows]
