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

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Any

from sqlalchemy import and_, exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventReviewStatus,
    EventStatus,
)
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.relation_repo import RelationRepository
from app.services.llm import call_llm_json

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
JACCARD_SAME_EVENT = 0.5
JACCARD_RELATED_TOPIC = 0.3
TEMPORAL_WINDOW_HOURS = 6
MAX_RELATIONS_PER_RUN = 500

# P2: LLM relation discovery — only for high-value items
LLM_DISCOVERY_SCORE_THRESHOLD = 70
LLM_DISCOVERY_MAX_CANDIDATES = 10
LLM_DISCOVERY_CONCURRENCY = 3


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
                ~_accepted_event_member_exists(),
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
                "curation_score": analysis.curation_score or 0,
                "summary": (analysis.summary or "")[:200],
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
    logger.info("Rule-based relations: %d items → %d relations %s", len(items), total, counts)

    # ── P2: LLM relation discovery for high-value items ──
    high_value = [i for i in items if i["curation_score"] >= LLM_DISCOVERY_SCORE_THRESHOLD]
    if high_value:
        llm_counts = await _discover_llm_relations(db, items, high_value)
        counts["causal"] = llm_counts.get("causal", 0)
        counts["response"] = llm_counts.get("response", 0)
        counts["contrast"] = llm_counts.get("contrast", 0)
        counts["total"] += llm_counts.get("total", 0)

    return counts


# ── P2: LLM relation discovery ────────────────────────────────────────


def _build_llm_prompt(target: dict[str, Any], candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Build the LLM prompt for relation type classification."""
    candidate_lines = []
    for c in candidates:
        summary = c.get("summary", "")[:100]
        candidate_lines.append(f"[{c['id']}] {c['title']} — {summary}")

    return [
        {
            "role": "user",
            "content": (
                "你是内容关联分析师。判断以下目标内容与每条候选内容的关系类型。\n\n"
                "关系类型：\n"
                "- causal: 目标是候选的原因/背景，或反过来（A 事件导致 B 发生）\n"
                "- response: 候选是对目标的回应、评论、观点输出\n"
                "- contrast: 候选与目标观点对立或呈现不同角度\n"
                "- none: 无明显关联\n\n"
                f"目标内容：[{target['id']}] {target['title']} — {target.get('summary', '')[:200]}\n\n"
                f"候选内容：\n{chr(10).join(candidate_lines)}\n\n"
                "只输出有关系（非 none）的，返回JSON：\n"
                '[{"target_id": 123, "type": "causal", "confidence": 0.8, "reason": "简述依据"}]\n'
                "规则：confidence 取 0.5-1.0；reason 不超过 30 字；没有关联返回空数组 []"
            ),
        }
    ]


async def _discover_llm_for_one(
    target: dict[str, Any],
    candidates: list[dict[str, Any]],
    repo: RelationRepository,
) -> dict[str, int]:
    """Run LLM relation discovery for a single target item."""
    prompt = _build_llm_prompt(target, candidates)
    try:
        data = await call_llm_json(
            prompt,
            temperature=0.15,
            max_tokens=800,
            scene="relation_discovery",
        )
        raw = data if isinstance(data, list) else data.get("relations", [])
        if not isinstance(raw, list):
            return {}

        valid_ids = {c["id"] for c in candidates}
        counts: dict[str, int] = {}

        for item in raw:
            if not isinstance(item, dict):
                continue
            target_id = item.get("target_id")
            rtype = item.get("type", "")
            if target_id not in valid_ids or rtype not in ("causal", "response", "contrast"):
                continue

            confidence = max(0.5, min(1.0, float(item.get("confidence", 0.7))))
            reason = str(item.get("reason", ""))[:100]

            await repo.upsert_relation(
                source_id=target["id"],
                target_id=target_id,
                relation_type=rtype,
                confidence=round(confidence, 3),
                evidence=f"LLM判定：{reason}",
            )
            counts[rtype] = counts.get(rtype, 0) + 1

        return counts
    except Exception as exc:
        logger.warning("LLM relation discovery failed for item %d: %s", target["id"], exc)
        return {}


async def _discover_llm_relations(
    db: AsyncSession,
    all_items: list[dict[str, Any]],
    high_value: list[dict[str, Any]],
) -> dict[str, int]:
    """
    Run LLM relation discovery on high-value items.

    For each high-value item, select top candidates by tag overlap,
    then ask LLM to classify the relationship type.
    """
    repo = RelationRepository(db)
    semaphore = asyncio.Semaphore(LLM_DISCOVERY_CONCURRENCY)
    total_counts: dict[str, int] = {}
    total = 0

    async def _run_one(target: dict[str, Any]) -> dict[str, int]:
        # Select candidates: different items, sorted by tag overlap
        others = [i for i in all_items if i["id"] != target["id"]]
        # Score by tag overlap with target
        scored = sorted(
            others,
            key=lambda o: len(o["tags"] & target["tags"]),
            reverse=True,
        )
        candidates = scored[:LLM_DISCOVERY_MAX_CANDIDATES]
        if not candidates:
            return {}

        async with semaphore:
            return await _discover_llm_for_one(target, candidates, repo)

    results = await asyncio.gather(*(_run_one(t) for t in high_value))

    for r in results:
        for k, v in r.items():
            total_counts[k] = total_counts.get(k, 0) + v
            total += v

    total_counts["total"] = total
    logger.info(
        "LLM relation discovery: %d high-value items → %d relations %s",
        len(high_value),
        total,
        total_counts,
    )
    return total_counts


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
