"""Topic clustering service.

Event normalization is owned exclusively by ``content_event_normalization``.
This service only groups related content into topics and optionally names those
topic groups with an LLM.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import UTC

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source
from app.models.topic import TopicGroup
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.services.feedback_signal import get_feedback_scores
from app.services.llm import call_llm_json
from app.services.scoring_engine import ScoringInput, score_items

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
CLUSTER_TAG_OVERLAP = 2  # min shared tags to be in same cluster (>=2 reduces false merges)
MIN_CLUSTER_SIZE = 2  # min items to form a topic group
CLUSTER_LLM_CONCURRENCY = 3

# ── Tag quality filter ─────────────────────────────────────────────────
# Stopwords that carry no topic signal — verbs, fillers, generic actions.
# These are excluded from clustering AND naming to prevent noise.
_TAG_STOPWORDS: frozenset[str] = frozenset({
    # Chinese filler / verbs
    "推出", "发布", "什么是", "如何", "为什么", "怎么",
    "解析", "分析", "解读", "盘点", "汇总", "一览",
    "新", "最", "热", "爆", "火", "全", "大",
    "看到", "发现", "说明", "表示", "认为", "指出",
    "进行", "开始", "继续", "已经", "正在", "可以",
    # English filler
    "studying", "discovered", "new", "best", "top",
    "how", "why", "what", "vs", "vs.",
})

# Tags shorter than this are too ambiguous for clustering (e.g. "AI", "5G")
# but still kept for display in keywords list.
_TAG_MIN_CLUSTER_LEN = 2
TOPIC_CLUSTERING_JOB_KEY = "topic_clustering"
TOPIC_CLUSTERING_JOB_NAME = "话题聚类"
TOPIC_CLUSTERING_JOB_TIMEOUT = 600
TOPIC_CLUSTERING_JOB_DESCRIPTION = "重建话题分组"


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


def _filter_clustering_tags(tags: set[str]) -> set[str]:
    """Filter tags for clustering: remove stopwords and too-short tags.

    Short tags (len < _TAG_MIN_CLUSTER_LEN) and stopwords are excluded
    from the *clustering* step to reduce false merges, but they may
    still appear in the keywords list for display.
    """
    return {
        t for t in tags
        if len(t) >= _TAG_MIN_CLUSTER_LEN and t not in _TAG_STOPWORDS
    }


def _union_find_cluster(
    items: list[dict],
) -> list[list[int]]:
    """Group items by tag overlap.

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

    # Use filtered tags for clustering to reduce false merges caused by
    # generic / stopword tags.  Unfiltered tags are still used for naming.
    tag_sets = [_filter_clustering_tags(_extract_tags(item)) for item in items]

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


# ── Optional LLM naming ────────────────────────────────────────────────


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
                "role": "system",
                "content": (
                    "你是一个话题命名助手。根据多篇内容标题和标签，"
                    "生成自然、准确的话题名称。\n\n"
                    "命名规则：\n"
                    "- 话题名必须是自然语言短语，不要用顿号/逗号拼接关键词\n"
                    "- 6-15字，概括核心主题而非罗列标签\n"
                    "- 优先提炼技术/产品/事件名称，避免使用动词\n"
                    "- 好例子：'大模型上下文缓存优化'、'宇树人形机器人量产'、'arXiv论文精选'\n"
                    "- 坏例子：'AI、模型'、'推出、发布'、'parser、pricing'\n"
                ),
            },
            {
                "role": "user",
                "content": (
                    "以下是同一话题的多篇内容标题：\n"
                    + "\n".join(f"- {t}" for t in titles)
                    + f"\n\n关键标签：{', '.join(top_tags)}\n\n"
                    "请为这个话题生成：\n"
                    "1. 话题名称（自然语言，6-15字）\n"
                    "2. 一句话摘要（20字以内）\n\n"
                    '返回JSON：{"name": "话题名", "summary": "一句话"}'
                ),
            },
        ]

        try:
            data = await call_llm_json(prompt, scene="topic_clustering")
            name = (data.get("name") or "").strip()[:30]
            summary = (data.get("summary") or "").strip()[:60]
            if not name:
                name = _auto_name_from_best_title(cluster)
        except Exception:
            name = _auto_name_from_best_title(cluster)
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


# ── Main entry point ────────────────────────────────────────────────────


async def cluster_topics_with_lease(
    db: AsyncSession,
    *,
    trigger_type: str = "manual",
    days: int = 7,
    use_llm_naming: bool = True,
) -> tuple[dict | None, bool]:
    """Run clustering under a cross-process lease.

    The clustering pass writes topic state, so overlapping runs must be
    skipped instead of allowed to interleave writes.
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
        stats = await cluster_topics(
            db,
            days=days,
            use_llm_naming=use_llm_naming,
        )
        # After clustering, discover content relations (zero LLM cost, runs in same session)
        try:
            from app.services.relation_engine import discover_relations

            relation_stats = await discover_relations(db, hours=days * 24)
            stats["relations"] = relation_stats
        except Exception:
            logger.warning("Relation discovery failed after clustering", exc_info=True)
        return stats, True
    except Exception:
        status = "FAILED"
        raise
    finally:
        await job_tracker._release_job_run(TOPIC_CLUSTERING_JOB_KEY, status)


def _auto_name_from_best_title(cluster: list[dict]) -> str:
    """Fallback: use the best-scoring item's title (truncated) as topic name.

    This produces far more natural names than tag concatenation
    (e.g. '荣耀 Robot Phone 手机搭载 Agentic OS' vs 'AI、模型').
    """
    best = max(cluster, key=lambda x: x.get("adjusted_score", x.get("curation_score", 0)))
    title = (best.get("title") or "").strip()
    if not title:
        return "未命名话题"
    # Truncate at a natural break point if possible
    if len(title) <= 15:
        return title
    # Try to cut at a punctuation mark near 15 chars
    for i in range(15, min(len(title), 25)):
        if title[i] in "，、：—— ー·,":
            return title[:i].rstrip("，、：—— ー·,")
    return title[:15]


def _auto_name_group(cluster: list[dict]) -> dict:
    """Generate topic metadata without calling LLM.

    Uses the best-scoring item's title as the topic name instead of
    mechanically concatenating tags, producing natural-language names.
    """
    tags_union: set[str] = set()
    for item in cluster:
        tags_union |= _extract_tags(item)
    top_tags = list(tags_union)[:4]
    best = max(cluster, key=lambda x: x.get("adjusted_score", x.get("curation_score", 0)))
    name = _auto_name_from_best_title(cluster)
    return {
        "name": name,
        "summary": "",
        "keywords": top_tags,
        "item_ids": [item["id"] for item in cluster],
        "best_score": best.get("adjusted_score", best.get("curation_score", 0)),
        "content_count": len(cluster),
    }


async def cluster_topics(
    db: AsyncSession,
    *,
    days: int = 7,
    use_llm_naming: bool = True,
) -> dict:
    """Run clustering on recent unassigned content. Returns stats.

    Incremental mode: only processes ANALYZED items created within ``days``
    that have no ``topic_id`` yet. Already-assigned items and existing
    TopicGroups are left untouched.

    LLM naming is ON by default (with auto-name fallback when LLM is
    unavailable). Event membership is deliberately not inferred here.
    """

    # 1. Fetch recent analyzed items that still lack a topic_id
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=days)
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
    result = await db.execute(
        select(ContentItem, AiAnalysis, Source.weight.label("source_weight_db"))
        .select_from(ContentItem)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .outerjoin(Source, Source.id == ContentItem.source_id)
        .where(
            and_(
                ContentItem.status == ContentStatus.ANALYZED,
                ContentItem.topic_id.is_(None),
                ContentItem.created_at >= cutoff,
            )
        )
        .order_by(ContentItem.id)
    )
    rows = result.all()

    if not rows:
        return {
            "clusters": 0,
            "standalone": 0,
            "total": 0,
            "window_days": days,
            "incremental": True,
        }

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

    # 2. Incremental: do NOT clear old topic assignments.
    #    Only new TopicGroups are inserted; existing ones are preserved.
    from sqlalchemy import text

    # 3. Tag-based topic clustering. Event membership is handled elsewhere.
    groups = _union_find_cluster(items)
    item_by_id = {item["id"]: item for item in items}

    # 4. Name clusters
    #    Default: auto-name from tag union (no LLM, instant).
    #    Optional: LLM naming for top N groups by size (use_llm_naming=True).
    cluster_meta = []
    if groups:
        sorted_groups = sorted(groups, key=len, reverse=True)

        if use_llm_naming:
            MAX_LLM_NAMED_CLUSTERS = 20
            llm_groups = sorted_groups[:MAX_LLM_NAMED_CLUSTERS]
            auto_groups = sorted_groups[MAX_LLM_NAMED_CLUSTERS:]

            if llm_groups:
                group_items = [
                    [item_by_id[item_id] for item_id in group]
                    for group in llm_groups
                ]
                cluster_meta = await _name_clusters(group_items)

            for group_ids in auto_groups:
                cluster = [item_by_id[item_id] for item_id in group_ids]
                cluster_meta.append(_auto_name_group(cluster))
            if auto_groups:
                logger.info("Auto-named %d overflow clusters (beyond LLM cap %d)", len(auto_groups), MAX_LLM_NAMED_CLUSTERS)
        else:
            # Fast path: auto-name all groups from tags (zero LLM calls)
            for group_ids in sorted_groups:
                cluster = [item_by_id[item_id] for item_id in group_ids]
                cluster_meta.append(_auto_name_group(cluster))

    # 5. Write to DB
    standalone_ids = {item["id"] for item in items} - {
        content_id for group in groups for content_id in group
    }

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

    await db.commit()

    stats = {
        "clusters": len(cluster_meta),
        "standalone": len(standalone_ids),
        "total": len(items),
        "window_days": days,
        "incremental": True,
    }
    logger.info("Clustering done: %s", stats)
    return stats
