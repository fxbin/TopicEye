"""
Rule-based relation discovery engine.

Discovers typed relationships between content items using
deterministic rules (no LLM cost):

  1. same_event:       Jaccard(tags) > 0.5 AND same topic_id AND different source
  2. related_topic:    Jaccard(tags) > 0.3 AND same topic_id AND NOT same_event
  3. temporal_cluster: same category AND within 6h crawl window AND different topic_id

Rules are intentionally cheap so they can run in the clustering job
without additional LLM calls.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.relation_repo import RelationRepository

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
JACCARD_SAME_EVENT = 0.5
JACCARD_RELATED_TOPIC = 0.3
TEMPORAL_WINDOW_HOURS = 6
MAX_RELATIONS_PER_RUN = 500


def _extract_tag_set(tags_raw: Any) -> set[str]:
    if not tags_raw:
        return set()
    if isinstance(tags_raw, str):
        try:
            tags_raw = json.loads(tags_raw)
        except (json.JSONDecodeError, TypeError):
            return set()
    if not isinstance(tags_raw, list):
        return set()
    return {str(t).strip().lower() for t in tags_raw if str(t).strip()}


def _jaccard(a: set[str], b: set[str]) -> float:
    union = a | b
    if not union:
        return 0.0
    return len(a & b) / len(union)


async def discover_relations(
    db: AsyncSession,
    *,
    hours: int = 48,
) -> dict[str, int]:
    """
    Run rule-based relation discovery on recent analyzed content.

    Returns {"same_event": N, "related_topic": M, "temporal_cluster": K, "total": T}.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)

    result = await db.execute(
        select(ContentItem, AiAnalysis)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(
            and_(
                ContentItem.status == ContentStatus.ANALYZED,
                ContentItem.crawled_at >= cutoff,
                ContentItem.duplicate_of.is_(None),
            )
        )
        .order_by(ContentItem.crawled_at.desc())
        .limit(200)
    )
    rows = result.all()

    if len(rows) < 2:
        return {"same_event": 0, "related_topic": 0, "temporal_cluster": 0, "total": 0}

    # Build item dicts for pairwise comparison
    items: list[dict[str, Any]] = []
    for content, analysis in rows:
        items.append(
            {
                "id": content.id,
                "title": content.title,
                "source_id": content.source_id,
                "source_name": content.source_name,
                "topic_id": content.topic_id,
                "category": content.category,
                "crawled_at": content.crawled_at,
                "tags": _extract_tag_set(analysis.tags),
            }
        )

    repo = RelationRepository(db)
    counts = {"same_event": 0, "related_topic": 0, "temporal_cluster": 0}
    total = 0

    for a, b in combinations(items, 2):
        if total >= MAX_RELATIONS_PER_RUN:
            break

        # Skip if same source (same source → likely duplicate, handled elsewhere)
        same_source = a["source_id"] and a["source_id"] == b["source_id"]

        # Rule 1 & 2: tag-based (requires same topic_id)
        if a["topic_id"] and a["topic_id"] == b["topic_id"] and not same_source:
            jaccard = _jaccard(a["tags"], b["tags"])
            if jaccard >= JACCARD_SAME_EVENT:
                await repo.upsert_relation(
                    source_id=a["id"],
                    target_id=b["id"],
                    relation_type="same_event",
                    confidence=round(jaccard, 3),
                    evidence=f"标签Jaccard={jaccard:.2f}，同话题且不同源",
                )
                counts["same_event"] += 1
                total += 1
            elif jaccard >= JACCARD_RELATED_TOPIC:
                await repo.upsert_relation(
                    source_id=a["id"],
                    target_id=b["id"],
                    relation_type="related_topic",
                    confidence=round(jaccard, 3),
                    evidence=f"标签Jaccard={jaccard:.2f}，同话题",
                )
                counts["related_topic"] += 1
                total += 1

        # Rule 3: temporal cluster (same category, different topic, within 6h)
        if (
            a["category"]
            and a["category"] == b["category"]
            and a["topic_id"] != b["topic_id"]
            and a["crawled_at"]
            and b["crawled_at"]
        ):
            delta = abs((a["crawled_at"] - b["crawled_at"]).total_seconds()) / 3600
            if delta <= TEMPORAL_WINDOW_HOURS:
                confidence = round(1.0 - delta / TEMPORAL_WINDOW_HOURS, 3)
                await repo.upsert_relation(
                    source_id=a["id"],
                    target_id=b["id"],
                    relation_type="temporal_cluster",
                    confidence=confidence,
                    evidence=f"同分类「{a['category']}」，时间差{delta:.1f}h",
                )
                counts["temporal_cluster"] += 1
                total += 1

    counts["total"] = total
    logger.info("Relation discovery: %d items → %d relations %s", len(items), total, counts)
    return counts
