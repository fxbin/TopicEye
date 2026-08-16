"""Daily trend snapshots and their public, drill-through evidence."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)
from app.models.content_evidence import ContentEvidenceMark
from app.models.source import Source
from app.models.topic import TopicGroup
from app.models.trend import TopicTrend, TopicTrendMember
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.trend_repo import TrendRepository
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import ScoringInput, score_items

logger = logging.getLogger(__name__)

TREND_CALCULATION_VERSION = "trend-v2"
EvidenceFilter = Literal["all", "selected", "evidenced"]


def _accepted_event_member_exists():
    return exists(
        select(ContentEventMember.id)
        .join(
            ContentEventGroup,
            ContentEventGroup.id == ContentEventMember.event_group_id,
        )
        .where(
            ContentEventMember.content_id == ContentItem.id,
            ContentEventGroup.status == EventStatus.ACTIVE,
            ContentEventMember.review_status.in_((EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED)),
        )
    )


def _time_basis(row) -> str:
    if row.published_at is not None:
        return "published_at"
    # `crawled_at` is non-null on ContentItem and is frozen in the member.
    # Do not claim a created_at fallback unless that field is also frozen.
    return "crawled_at"


def _member_values(
    row,
    *,
    position: int,
    score: float | None = None,
    selected: bool = False,
) -> dict:
    """Freeze the fields needed to explain a member after its content is deleted."""
    return {
        "content_id": row.id,
        "position": position,
        "score": round(score, 1) if score is not None else None,
        "selected": selected,
        "title_snapshot": row.title or "",
        "url_snapshot": row.url or "",
        "source_id_snapshot": row.source_id,
        "source_name_snapshot": row.source_name,
        "source_type_snapshot": row.source_type,
        "platform_snapshot": row.platform,
        "published_at_snapshot": row.published_at,
        "crawled_at_snapshot": row.crawled_at,
        "time_basis": _time_basis(row),
    }


def _parse_distinct_tags(tags_json) -> set[str]:
    """Normalize one analysis tag payload without letting repeated tags double count."""
    if not tags_json:
        return set()
    try:
        values = tags_json if isinstance(tags_json, list) else json.loads(tags_json)
    except (TypeError, ValueError, json.JSONDecodeError):
        logger.warning("Skipping malformed trend tags payload")
        return set()
    if not isinstance(values, list):
        return set()
    return {tag.strip() for tag in values if isinstance(tag, str) and tag.strip()}


async def snapshot_daily_trends(db: AsyncSession, target_date: date | None = None) -> dict:
    """Compute public topic/keyword snapshots and atomically freeze their members."""
    if target_date is None:
        target_date = date.today()

    start_dt = datetime.combine(target_date, datetime.min.time(), tzinfo=UTC)
    end_dt = datetime.combine(target_date + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
    repo = TrendRepository(db)
    await repo.delete_by_date(target_date)

    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
    trend_row_columns = (
        ContentItem.id,
        ContentItem.title,
        ContentItem.url,
        ContentItem.category,
        ContentItem.source_id,
        ContentItem.source_name,
        ContentItem.source_type,
        ContentItem.platform,
        ContentItem.published_at,
        ContentItem.crawled_at,
        ContentItem.created_at,
    )

    topic_rows_result = await db.execute(
        select(
            ContentItem.topic_id,
            TopicGroup.name.label("topic_name"),
            *trend_row_columns,
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
        .outerjoin(TopicGroup, TopicGroup.id == ContentItem.topic_id)
        .where(
            and_(
                ContentItem.owner_user_id.is_(None),
                ContentItem.topic_id.isnot(None),
                ~_accepted_event_member_exists(),
                ContentItem.created_at >= start_dt,
                ContentItem.created_at < end_dt,
            )
        )
    )
    topic_items: dict[int, list] = {}
    content_ids: list[int] = []
    for row in topic_rows_result:
        topic_items.setdefault(row.topic_id, []).append(row)
        content_ids.append(row.id)

    feedback_scores = await get_feedback_scores(db, content_ids)
    topic_count = 0
    created_snapshots: list[TopicTrend] = []
    for topic_id, rows in topic_items.items():
        scored_items = score_items([_trend_row_to_scoring_input(row, feedback_scores.get(row.id, 0)) for row in rows])
        row_map = {row.id: row for row in rows}
        member_values = [
            _member_values(
                row_map[item.content_id],
                position=position,
                score=breakdown.final_score or 0,
                selected=bool(breakdown.selected),
            )
            for position, (breakdown, item) in enumerate(scored_items, start=1)
        ]
        final_scores = [values["score"] or 0 for values in member_values]
        snapshot = TopicTrend(
            snapshot_date=target_date,
            topic_id=topic_id,
            topic_name=rows[0].topic_name or f"Topic-{topic_id}",
            content_count=len(member_values),
            avg_score=round(sum(final_scores) / len(final_scores), 1) if final_scores else 0,
            max_score=round(max(final_scores), 1) if final_scores else 0,
            pick_count=sum(1 for values in member_values if values["selected"]),
            top_items=[
                {
                    "title": values["title_snapshot"],
                    "url": values["url_snapshot"],
                    "score": values["score"],
                }
                for values in member_values[:3]
            ],
            calculation_version=TREND_CALCULATION_VERSION,
            window_start=start_dt,
            window_end=end_dt,
            provenance_status="unavailable",
        )
        await repo.add_snapshot_with_members(snapshot, member_values)
        created_snapshots.append(snapshot)
        topic_count += 1

    keyword_rows_result = await db.execute(
        select(*trend_row_columns, AiAnalysis.tags)
        .select_from(ContentItem)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(
            and_(
                ContentItem.owner_user_id.is_(None),
                AiAnalysis.tags.isnot(None),
                ~_accepted_event_member_exists(),
                ContentItem.created_at >= start_dt,
                ContentItem.created_at < end_dt,
            )
        )
    )
    keyword_items: dict[str, list] = {}
    for row in keyword_rows_result:
        for keyword in _parse_distinct_tags(row.tags):
            keyword_items.setdefault(keyword, []).append(row)

    keyword_count = 0
    for keyword, rows in sorted(keyword_items.items(), key=lambda item: (-len(item[1]), item[0]))[:50]:
        ordered_rows = sorted(
            rows,
            key=lambda row: (row.published_at or row.crawled_at or row.created_at, row.id),
            reverse=True,
        )
        member_values = [_member_values(row, position=position) for position, row in enumerate(ordered_rows, start=1)]
        snapshot = TopicTrend(
            snapshot_date=target_date,
            keyword=keyword,
            content_count=len(member_values),
            avg_score=0,
            max_score=0,
            pick_count=0,
            calculation_version=TREND_CALCULATION_VERSION,
            window_start=start_dt,
            window_end=end_dt,
            provenance_status="unavailable",
        )
        await repo.add_snapshot_with_members(snapshot, member_values)
        created_snapshots.append(snapshot)
        keyword_count += 1

    await db.flush()
    for snapshot in created_snapshots:
        member_count = await repo.count_members(snapshot.id)
        if member_count != snapshot.content_count:
            raise RuntimeError(
                f"Trend snapshot {snapshot.id} member mismatch: " f"{member_count} != {snapshot.content_count}"
            )
        snapshot.provenance_status = "complete"

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


def _provenance_from_statuses(statuses: set[str]) -> str:
    if statuses == {"complete"}:
        return "complete"
    if "complete" in statuses or "sample_only" in statuses:
        return "partial"
    return "unavailable"


def _scope_provenance_status(snapshots: list[TopicTrend]) -> str:
    return _provenance_from_statuses({snapshot.provenance_status for snapshot in snapshots})


def _calculation_payload(snapshots: list[TopicTrend]) -> dict:
    versions = {snapshot.calculation_version for snapshot in snapshots}
    window_starts = [snapshot.window_start for snapshot in snapshots if snapshot.window_start]
    window_ends = [snapshot.window_end for snapshot in snapshots if snapshot.window_end]
    generated_at = [snapshot.created_at for snapshot in snapshots if snapshot.created_at]
    return {
        "version": next(iter(versions)) if len(versions) == 1 else "mixed",
        "generated_at": max(generated_at) if generated_at else None,
        "window_start": min(window_starts) if window_starts else None,
        "window_end": max(window_ends) if window_ends else None,
        "event_members_excluded": True,
    }


def _serialize_mark(mark: ContentEvidenceMark | None) -> dict | None:
    if mark is None:
        return None
    return {
        "cross_source_level": mark.cross_source_level,
        "platform_count": mark.platform_count,
        "platforms": mark.platforms or [],
        "evidence_count": mark.evidence_count,
        "independent_publisher_count": mark.independent_publisher_count,
        "has_primary_source": bool(mark.has_primary_source),
        "has_official_source": bool(mark.has_official_source),
    }


def _serialize_member(member: TopicTrendMember, mark: ContentEvidenceMark | None) -> dict:
    return {
        "content_id": member.content_id,
        "title": member.title_snapshot,
        "url": member.url_snapshot,
        "source_id": member.source_id_snapshot,
        "source_name": member.source_name_snapshot,
        "source_type": member.source_type_snapshot,
        "platform": member.platform_snapshot,
        "published_at": member.published_at_snapshot,
        "crawled_at": member.crawled_at_snapshot,
        "time_basis": member.time_basis,
        "score": member.score,
        "selected": member.selected,
        "evidence_mark": _serialize_mark(mark),
    }


def _history_message(status: str) -> str | None:
    if status == "sample_only":
        return "该历史快照仅保留代表内容，无法恢复完整构成。"
    if status == "partial":
        return "所选范围包含未保存构成明细的历史快照，仅展示可恢复的部分。"
    if status == "unavailable":
        return "该历史快照生成时未保存构成明细。"
    return None


async def _evidence_payload(
    db: AsyncSession,
    *,
    snapshots: list[TopicTrend],
    kind: Literal["topic", "keyword"],
    key: str,
    label: str,
    start_date: date,
    end_date: date,
    evidence_filter: EvidenceFilter,
    page: int,
    page_size: int,
) -> dict:
    provenance_status = snapshots[0].provenance_status if kind == "topic" else _scope_provenance_status(snapshots)
    complete_snapshots = [snapshot for snapshot in snapshots if snapshot.provenance_status == "complete"]
    repo = TrendRepository(db)
    trend_ids = [snapshot.id for snapshot in complete_snapshots]

    summary = await repo.summarize_members(trend_ids)
    rows, total = await repo.list_members(
        trend_ids,
        evidence_filter=evidence_filter,
        page=page,
        page_size=page_size,
        keyword_order=kind == "keyword",
    )
    daily_counts = [
        {
            "date": snapshot.snapshot_date,
            "count": snapshot.content_count,
            "provenance_status": snapshot.provenance_status,
        }
        for snapshot in sorted(snapshots, key=lambda snapshot: snapshot.snapshot_date)
    ]
    summary["provenance_status"] = provenance_status
    return {
        "scope": {
            "kind": kind,
            "key": key,
            "label": label,
            "start_date": start_date,
            "end_date": end_date,
        },
        "summary": summary,
        "calculation": _calculation_payload(snapshots),
        "daily_counts": daily_counts,
        "items": [_serialize_member(member, mark) for member, mark in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
        "message": _history_message(provenance_status),
    }


async def get_topic_trend_evidence(
    db: AsyncSession,
    *,
    topic_id: int,
    snapshot_date: date,
    evidence_filter: EvidenceFilter = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict | None:
    """Return the public frozen members for one topic-day snapshot."""
    snapshot = await TrendRepository(db).get_topic_snapshot(topic_id, snapshot_date)
    if snapshot is None:
        return None
    return await _evidence_payload(
        db,
        snapshots=[snapshot],
        kind="topic",
        key=str(topic_id),
        label=snapshot.topic_name or f"Topic-{topic_id}",
        start_date=snapshot_date,
        end_date=snapshot_date,
        evidence_filter=evidence_filter,
        page=page,
        page_size=page_size,
    )


async def get_keyword_trend_evidence(
    db: AsyncSession,
    *,
    keyword: str,
    days: int = 7,
    evidence_filter: EvidenceFilter = "all",
    page: int = 1,
    page_size: int = 20,
) -> dict | None:
    """Return public frozen members for a keyword across the requested interval."""
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    snapshots = list(await TrendRepository(db).get_keyword_snapshots(keyword, start_date, end_date))
    if not snapshots:
        return None
    return await _evidence_payload(
        db,
        snapshots=snapshots,
        kind="keyword",
        key=keyword,
        label=keyword,
        start_date=start_date,
        end_date=end_date,
        evidence_filter=evidence_filter,
        page=page,
        page_size=page_size,
    )


async def get_topic_trends(db: AsyncSession, days: int = 7) -> list[dict]:
    """Compatibility read path for callers that do not use DuckDB."""
    cutoff = date.today() - timedelta(days=days)
    rows = await db.execute(
        select(TopicTrend)
        .where(and_(TopicTrend.topic_id.isnot(None), TopicTrend.snapshot_date >= cutoff))
        .order_by(TopicTrend.snapshot_date, TopicTrend.topic_id)
    )
    return [
        {
            "date": trend.snapshot_date.isoformat(),
            "snapshot_id": trend.id,
            "topic_id": trend.topic_id,
            "topic_name": trend.topic_name,
            "content_count": trend.content_count,
            "avg_score": trend.avg_score,
            "max_score": trend.max_score,
            "pick_count": trend.pick_count,
            "top_items": trend.top_items,
            "provenance_status": trend.provenance_status,
            "generated_at": trend.created_at,
            "calculation_version": trend.calculation_version,
        }
        for trend in rows.scalars().all()
    ]


async def get_keyword_cloud(db: AsyncSession, days: int = 7, limit: int = 50) -> list[dict]:
    """Compatibility keyword aggregation with traceability metadata."""
    cutoff = date.today() - timedelta(days=days)
    rows = await db.execute(
        select(
            TopicTrend.keyword,
            TopicTrend.content_count,
            TopicTrend.provenance_status,
        ).where(and_(TopicTrend.keyword.isnot(None), TopicTrend.snapshot_date >= cutoff))
    )
    aggregates: dict[str, dict] = {}
    for row in rows:
        aggregate = aggregates.setdefault(row.keyword, {"count": 0, "statuses": set()})
        aggregate["count"] += int(row.content_count)
        aggregate["statuses"].add(row.provenance_status)
    return [
        {
            "keyword": keyword,
            "count": values["count"],
            "traceability": _provenance_from_statuses(values["statuses"]),
        }
        for keyword, values in sorted(aggregates.items(), key=lambda item: (-item[1]["count"], item[0]))[:limit]
    ]
