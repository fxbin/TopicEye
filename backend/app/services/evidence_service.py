"""
Cross-source evidence discovery service.

Phase 1 MVP: detect cross-platform same-event signals using
tag overlap + title keyword matching (zero LLM by default).

Algorithm:
  1. Fetch recent analyzed items in the visibility scope
  2. For each pair, check tag overlap and time window
  3. Group same-event items into event groups
  4. Count distinct platforms (source_type) and independent publishers
  5. Persist marks and links bidirectionally for all group members
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from itertools import combinations
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_evidence import CrossSourceLevel, EvidenceType
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.evidence_repo import EvidenceRepository

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
TAG_OVERLAP_SAME_EVENT = 2  # min shared tags to be candidate
TAG_OVERLAP_RELATED = 1  # min shared tags to be borderline candidate
TIME_WINDOW_HOURS = 12
TIME_WINDOW_EXTENDED_HOURS = 24
MAX_ITEMS_PER_RUN = 200
MIN_PLATFORMS_FOR_SIGNAL = 2
MIN_PLATFORMS_FOR_STRONG = 3


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


def _extract_title_keywords(title: str, min_len: int = 3) -> set[str]:
    """Extract keywords from title (simple split + filter)."""
    if not title:
        return set()
    import re

    words = re.findall(r"[\w\u4e00-\u9fff]{2,}", title.lower())
    return {w for w in words if len(w) >= min_len}


def _get_platform(source_type: str | None, source_name: str | None) -> str:
    """Determine platform from source_type/source_name."""
    if source_type:
        st = source_type.lower()
        if "rss" in st or "web" in st or "html" in st:
            return "website"
        return st
    if source_name:
        sn = source_name.lower()
        for platform in ("x", "twitter", "weibo", "github", "youtube", "bilibili"):
            if platform in sn:
                return "x" if platform == "twitter" else platform
    return "unknown"


async def discover_cross_source_evidence(
    db: AsyncSession,
    *,
    hours: int = 24,
    owner_user_id: int | None = None,
) -> dict[str, int]:
    """
    Run cross-source evidence discovery on recent analyzed content.

    Returns {"groups": N, "marks": M, "links": L, "total": T}.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)

    # Visibility scope
    owner_filter = (
        ContentItem.owner_user_id.is_(None) if owner_user_id is None else ContentItem.owner_user_id == owner_user_id
    )

    result = await db.execute(
        select(ContentItem, AiAnalysis)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(
            and_(
                ContentItem.status == ContentStatus.ANALYZED,
                ContentItem.crawled_at >= cutoff,
                ContentItem.duplicate_of.is_(None),
                owner_filter,
            )
        )
        .order_by(ContentItem.crawled_at.desc())
        .limit(MAX_ITEMS_PER_RUN)
    )
    rows = result.all()

    if len(rows) < 2:
        return {"groups": 0, "marks": 0, "links": 0, "total": 0}

    # Build item dicts
    items: list[dict[str, Any]] = []
    for content, analysis in rows:
        tags = _extract_tag_set(analysis.tags)
        keywords = _extract_title_keywords(content.title)
        items.append(
            {
                "id": content.id,
                "title": content.title,
                "url": content.url,
                "source_id": content.source_id,
                "source_name": content.source_name,
                "source_type": str(content.source_type) if content.source_type else None,
                "platform": _get_platform(content.source_type, content.source_name),
                "crawled_at": content.crawled_at,
                "published_at": content.published_at,
                "tags": tags,
                "keywords": keywords,
            }
        )

    # ── Candidate pairing: tag overlap + time window ──
    # Group items by shared tags (union-find style)
    parent: dict[int, int] = {item["id"]: item["id"] for item in items}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    item_by_id = {item["id"]: item for item in items}

    for a, b in combinations(items, 2):
        shared_tags = a["tags"] & b["tags"]
        shared_keywords = a["keywords"] & b["keywords"]
        if len(shared_tags) < TAG_OVERLAP_RELATED and len(shared_keywords) < 2:
            continue

        # Time window check
        ta = a["published_at"] or a["crawled_at"]
        tb = b["published_at"] or b["crawled_at"]
        if not ta or not tb:
            continue
        delta_hours = abs((ta - tb).total_seconds()) / 3600
        if delta_hours > TIME_WINDOW_EXTENDED_HOURS:
            continue

        union(a["id"], b["id"])

    # ── Build event groups ──
    groups: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        root = find(item["id"])
        groups[root].append(item)

    # Filter groups with < 2 members
    event_groups = [g for g in groups.values() if len(g) >= 2]

    if not event_groups:
        return {"groups": 0, "marks": 0, "links": 0, "total": len(items)}

    repo = EvidenceRepository(db)
    total_marks = 0
    total_links = 0

    for group in event_groups:
        # Count distinct platforms
        platforms = {item["platform"] for item in group}
        # Count distinct source_ids (independent publishers)
        source_ids = {item["source_id"] for item in group if item["source_id"]}

        if len(platforms) < MIN_PLATFORMS_FOR_SIGNAL:
            continue

        # Determine cross_source_level
        if len(platforms) >= MIN_PLATFORMS_FOR_STRONG:
            level = CrossSourceLevel.STRONG_CROSS_SOURCE
        else:
            level = CrossSourceLevel.CROSS_SOURCE

        platform_list = sorted(platforms)
        independent_count = len(source_ids)

        # Persist marks for all items in the group (bidirectional)
        for item in group:
            mark = await repo.upsert_mark(
                content_id=item["id"],
                owner_user_id=owner_user_id,
                cross_source_level=level,
                platform_count=len(platforms),
                platforms=platform_list,
                evidence_count=len(group) - 1,
                independent_publisher_count=independent_count,
            )

            # Delete old links and re-add
            await repo.delete_links_for_mark(mark.id)
            total_marks += 1

            # Add links to other group members
            for other in group:
                if other["id"] == item["id"]:
                    continue
                ta = item["published_at"] or item["crawled_at"]
                tb = other["published_at"] or other["crawled_at"]
                delta_min = abs((ta - tb).total_seconds()) / 60 if ta and tb else None

                shared = item["tags"] & other["tags"]
                basis = "tags" if len(shared) >= TAG_OVERLAP_SAME_EVENT else "title_keywords"

                await repo.add_link(
                    mark_id=mark.id,
                    evidence_content_id=other["id"],
                    evidence_url=other.get("url"),
                    evidence_type=EvidenceType.CROSS_SOURCE,
                    publisher_family=other.get("source_name"),
                    source_id=other.get("source_id"),
                    similarity_score=round(len(shared) / max(len(item["tags"] | other["tags"]), 1), 3) if shared else 0.3,
                    time_delta_minutes=delta_min,
                    match_basis=basis,
                )
                total_links += 1

    stats = {
        "groups": len(event_groups),
        "marks": total_marks,
        "links": total_links,
        "total": len(items),
    }
    logger.info(
        "Cross-source evidence: %d items → %d groups → %d marks, %d links",
        len(items),
        len(event_groups),
        total_marks,
        total_links,
    )
    return stats
