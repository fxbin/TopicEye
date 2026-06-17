"""
Topic clustering service — AI semantic dedup + semantic grouping.

Algorithm:
  1. AI semantic dedup: LLM on title+summary+tags → same-event pairs (replaces SequenceMatcher)
  2. Tag-based clustering: shared tags → same topic
  3. LLM naming: one call per cluster for topic name + summary
"""

from __future__ import annotations

import json
import logging
import asyncio
from collections import defaultdict
from typing import Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem, ContentStatus
from app.models.analysis import AiAnalysis
from app.models.source import Source
from app.models.topic import TopicGroup
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.services.feedback_signal import get_feedback_scores
from app.services.llm import call_llm_json
from app.services.scoring_engine import ScoringInput, score_items
from app.services.semantic_dedup import semantic_dedup

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
CLUSTER_TAG_OVERLAP = 1  # min shared tags to be in same cluster
MIN_CLUSTER_SIZE = 2  # min items to form a topic group
CLUSTER_LLM_CONCURRENCY = 3
TOPIC_CLUSTERING_JOB_KEY = "topic_clustering"
TOPIC_CLUSTERING_JOB_NAME = "话题聚类与去重"
TOPIC_CLUSTERING_JOB_TIMEOUT = 600
TOPIC_CLUSTERING_JOB_DESCRIPTION = "重建话题分组和语义去重关系"


# ── Tag-based clustering ────────────────────────────────────────────────


def _extract_tags(item: dict) -> set[str]:
    """Extract normalized tag set from item's analysis tags."""
    raw = item.get("tags", [])
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            raw = []
    if not isinstance(raw, list):
        raw = []
    return {str(t).strip().lower() for t in raw if str(t).strip()}


def _union_find_cluster(
    items: list[dict],
) -> list[list[int]]:
    """Group non-duplicate items by tag overlap.

    Returns list of groups, each group is a list of item IDs.
    """
    n = len(items)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    tag_sets = [_extract_tags(item) for item in items]

    if CLUSTER_TAG_OVERLAP <= 1:
        # Fast path for the current product rule: any shared tag connects items.
        # This avoids the previous O(n^2) pairwise scan on large analyzed corpora.
        tag_index: dict[str, list[int]] = defaultdict(list)
        for idx, tags in enumerate(tag_sets):
            for tag in tags:
                tag_index[tag].append(idx)

        for indices in tag_index.values():
            if len(indices) < 2:
                continue
            anchor = indices[0]
            for idx in indices[1:]:
                union(anchor, idx)
    else:
        # Generic fallback if the overlap threshold is raised later.
        for i in range(n):
            if not tag_sets[i]:
                continue
            for j in range(i + 1, n):
                if not tag_sets[j]:
                    continue
                overlap = len(tag_sets[i] & tag_sets[j])
                if overlap >= CLUSTER_TAG_OVERLAP:
                    union(i, j)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(items[i]["id"])

    return [g for g in groups.values() if len(g) >= MIN_CLUSTER_SIZE]


# ── Step 3: LLM naming ─────────────────────────────────────────────────


async def _name_clusters(
    clusters: list[list[dict]],
) -> list[dict]:
    """Call LLM to name each cluster. Returns list of cluster metadata."""
    semaphore = asyncio.Semaphore(CLUSTER_LLM_CONCURRENCY)

    async def _name_one_cluster(cluster: list[dict]) -> dict:
        titles = [item["title"] for item in cluster[:10]]
        tags_union: set[str] = set()
        for item in cluster:
            tags_union |= _extract_tags(item)
        top_tags = list(tags_union)[:8]

        prompt = [
            {
                "role": "user",
                "content": (
                    "以下是同一话题的多篇内容标题：\n"
                    + "\n".join(f"- {t}" for t in titles)
                    + f"\n\n关键标签：{', '.join(top_tags)}\n\n"
                    "请为这个话题生成：\n"
                    "1. 话题名称（8字以内，精炼概括）\n"
                    "2. 一句话摘要（20字以内）\n\n"
                    '返回JSON：{"name": "话题名", "summary": "一句话"}'
                ),
            }
        ]

        try:
            data = await call_llm_json(prompt, scene="topic_clustering")
            name = data.get("name", "未命名话题")[:20]
            summary = data.get("summary", "")[:50]
        except Exception:
            name = "、".join(top_tags[:2]) if top_tags else "未命名话题"
            summary = ""

        best = max(cluster, key=lambda x: x.get("adjusted_score", x.get("curation_score", 0)))
        return {
            "name": name,
            "summary": summary,
            "keywords": top_tags,
            "item_ids": [item["id"] for item in cluster],
            "best_score": best.get("adjusted_score", best.get("curation_score", 0)),
            "content_count": len(cluster),
        }

    async def _bounded_name(cluster: list[dict]) -> dict:
        async with semaphore:
            return await _name_one_cluster(cluster)

    return await asyncio.gather(*(_bounded_name(cluster) for cluster in clusters))


async def _dedup_candidate_clusters(cluster_items: list[list[dict]]) -> dict[int, int]:
    """Run semantic dedup on candidate clusters with bounded concurrency."""
    semaphore = asyncio.Semaphore(CLUSTER_LLM_CONCURRENCY)

    async def _dedup_one(cluster_item_list: list[dict]) -> dict[int, int]:
        async with semaphore:
            return await semantic_dedup(cluster_item_list)

    dedup_results = await asyncio.gather(*(_dedup_one(cluster) for cluster in cluster_items))
    dup_map: dict[int, int] = {}
    for cluster_dups in dedup_results:
        dup_map.update(cluster_dups)
    return dup_map


# ── Main entry point ────────────────────────────────────────────────────


async def cluster_and_dedup_with_lease(
    db: AsyncSession,
    *,
    trigger_type: str = "manual",
) -> tuple[Optional[dict], bool]:
    """Run clustering under a cross-process lease.

    The clustering pass clears and rebuilds topic/duplicate state, so overlapping
    runs must be skipped instead of allowed to interleave writes.
    """
    from app.services import job_tracker

    claimed = await job_tracker._claim_job_run(
        TOPIC_CLUSTERING_JOB_KEY,
        TOPIC_CLUSTERING_JOB_NAME,
        TOPIC_CLUSTERING_JOB_DESCRIPTION,
        TOPIC_CLUSTERING_JOB_TIMEOUT,
    )
    if not claimed:
        await job_tracker._record_skipped_job(
            TOPIC_CLUSTERING_JOB_KEY,
            trigger_type,
            "话题聚类仍在运行，本次触发已跳过",
        )
        return None, False

    status = "SUCCESS"
    try:
        stats = await cluster_and_dedup(db)
        return stats, True
    except Exception:
        status = "FAILED"
        raise
    finally:
        await job_tracker._release_job_run(TOPIC_CLUSTERING_JOB_KEY, status)


async def cluster_and_dedup(db: AsyncSession) -> dict:
    """Run dedup + clustering on all analyzed content. Returns stats."""

    # 1. Fetch all analyzed items with their latest analysis
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
    result = await db.execute(
        select(ContentItem, AiAnalysis, Source.weight.label("source_weight_db"))
        .select_from(ContentItem)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .outerjoin(Source, Source.id == ContentItem.source_id)
        .where(ContentItem.status == ContentStatus.ANALYZED)
        .order_by(ContentItem.id)
    )
    rows = result.all()

    if not rows:
        return {"clusters": 0, "duplicates": 0, "standalone": 0}

    content_ids = [content.id for content, _analysis, _source_weight in rows]
    feedback_scores = await get_feedback_scores(db, content_ids)
    items = []
    scoring_inputs = []
    for content, analysis, source_weight_db in rows:
        items.append(
            {
                "id": content.id,
                "title": content.title,
                "summary": analysis.summary or "",
                "tags": analysis.tags,
                "curation_score": analysis.curation_score or 0,
                "adjusted_score": analysis.curation_score or 0,
                "source_name": content.source_name,
            }
        )
        scoring_inputs.append(
            ScoringInput(
                content_id=content.id,
                title=content.title,
                category=content.category,
                source_id=content.source_id,
                source_name=content.source_name,
                published_at=content.published_at,
                crawled_at=content.crawled_at,
                curation_score=analysis.curation_score or 0,
                info_density=analysis.info_density or 50,
                actionability=analysis.actionability or 50,
                source_weight=analysis.source_weight or 50,
                creator_score=analysis.creator_score or 0,
                viral_score=analysis.viral_score or 0,
                freshness_score=analysis.freshness_score or 0,
                quality_score=analysis.quality_score or 0,
                hot_score=analysis.hot_score or 0,
                risk_score=analysis.risk_score or 0,
                source_weight_db=source_weight_db or 3,
                feedback_score=feedback_scores.get(content.id, 0),
            )
        )

    adjusted_scores = {item.content_id: breakdown.final_score for breakdown, item in score_items(scoring_inputs)}
    for item in items:
        item["adjusted_score"] = adjusted_scores.get(item["id"], item["curation_score"])

    # 2. Clear old topic assignments
    from sqlalchemy import text

    await db.execute(text("UPDATE content_items SET topic_id=NULL, duplicate_of=NULL, similarity_score=0.0"))
    await db.execute(text("DELETE FROM topic_groups"))
    await db.flush()

    # 3. Tag-based clustering (candidate scope for same-topic duplicates)
    #    Items without shared tags → standalone groups (will be skipped in dedup below)
    groups = _union_find_cluster(items)  # run on ALL items first
    item_by_id = {item["id"]: item for item in items}
    cluster_items_map: dict[int, list[dict]] = {}  # cluster_idx → items
    for idx, group_ids in enumerate(groups):
        cluster_items_map[idx] = [item_by_id[item_id] for item_id in group_ids]

    # 4. AI semantic dedup within candidate clusters
    #    Only small clusters (2-15 items) are candidates — same-event duplicates share tags
    dedup_candidates = []
    for idx, cluster_item_list in cluster_items_map.items():
        if len(cluster_item_list) < 2 or len(cluster_item_list) > 15:
            continue
        dedup_candidates.append(cluster_item_list)
    dup_map = await _dedup_candidate_clusters(dedup_candidates) if dedup_candidates else {}
    dup_count = len(dup_map)

    # 5. Non-duplicate items for clustering
    non_dup = [i for i in items if i["id"] not in dup_map]

    # 6. Re-cluster non-duplicate items (clean topic groups, standalone excluded)
    groups = _union_find_cluster(non_dup)

    # 7. LLM naming for clusters
    cluster_meta = []
    if groups:
        group_items = []
        non_dup_by_id = {item["id"]: item for item in non_dup}
        for group_ids in groups:
            cluster = [non_dup_by_id[item_id] for item_id in group_ids]
            group_items.append(cluster)
        cluster_meta = await _name_clusters(group_items)

    # 8. Write to DB
    standalone_ids = {i["id"] for i in non_dup} - {id for g in groups for id in g}

    for meta in cluster_meta:
        topic = TopicGroup(
            name=meta["name"],
            keywords=meta["keywords"],
            summary=meta["summary"],
            content_count=meta["content_count"],
            best_score=meta["best_score"],
        )
        db.add(topic)
        await db.flush()  # get topic.id

        for item_id in meta["item_ids"]:
            await db.execute(
                text("UPDATE content_items SET topic_id=:tid WHERE id=:id"),
                {"tid": topic.id, "id": item_id},
            )

    # Write duplicate mappings (similarity_score=1.0 for LLM-confirmed duplicates)
    for dup_id, canonical_id in dup_map.items():
        await db.execute(
            text("UPDATE content_items SET duplicate_of=:can_id, similarity_score=1.0 WHERE id=:id"),
            {"can_id": canonical_id, "id": dup_id},
        )

    await db.commit()

    stats = {
        "clusters": len(cluster_meta),
        "duplicates": dup_count,
        "standalone": len(standalone_ids),
        "total": len(items),
    }
    logger.info("Clustering done: %s", stats)
    return stats
