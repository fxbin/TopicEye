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

from app.core.config import settings
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_evidence import CrossSourceLevel, EvidenceType
from app.models.source_evidence_profile import PublisherKind, SourceEvidenceProfile
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.repositories.content_event_consumption_repo import (
    ContentEventConsumptionRepository,
    EvidenceContent,
    EvidenceEvent,
)
from app.repositories.evidence_repo import EvidenceRepository

logger = logging.getLogger(__name__)

# ── Thresholds ──────────────────────────────────────────────────────────
TAG_OVERLAP_SAME_EVENT = 2  # min shared tags to be candidate
TAG_OVERLAP_RELATED = 1  # min shared tags to be borderline candidate
TIME_WINDOW_HOURS = 12
TIME_WINDOW_EXTENDED_HOURS = 24
MAX_ITEMS_PER_RUN = 200
MAX_EVENT_EVIDENCE_MEMBERS = 20
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
    """Discover evidence through the staged event-truth rollout.

    ``off`` and ``shadow`` preserve the legacy detector. ``write`` additionally
    computes bounded comparison counters without changing persisted output.
    ``serve`` consumes only active event truth and falls back to legacy if that
    read path fails.
    """

    mode = str(settings.EVENT_NORMALIZATION_ROLLOUT_MODE or "off").lower()
    if mode != "serve":
        stats = await _discover_legacy_cross_source_evidence(
            db,
            hours=hours,
            owner_user_id=owner_user_id,
        )
        if mode == "write":
            try:
                comparison = await _compare_event_evidence(
                    db,
                    hours=hours,
                    owner_user_id=owner_user_id,
                )
                stats.update(comparison)
                logger.info(
                    "Evidence event-truth comparison: legacy_groups=%d event_groups=%d "
                    "event_evidence_members=%d",
                    stats["groups"],
                    comparison["event_compare_groups"],
                    comparison["event_compare_members"],
                )
            except Exception:
                logger.warning(
                    "Evidence event-truth comparison failed; legacy output preserved",
                    exc_info=True,
                )
                stats["event_compare_failed"] = 1
        return stats

    try:
        # Event serving performs replacement writes. A savepoint guarantees
        # that any partial canonical/member cleanup is rolled back before the
        # legacy fallback runs.
        async with db.begin_nested():
            return await _discover_event_cross_source_evidence(
                db,
                hours=hours,
                owner_user_id=owner_user_id,
            )
    except Exception:
        logger.warning(
            "Event-truth evidence read failed; falling back to legacy discovery",
            exc_info=True,
        )
        stats = await _discover_legacy_cross_source_evidence(
            db,
            hours=hours,
            owner_user_id=owner_user_id,
        )
        stats["event_fallback"] = 1
        return stats


async def _discover_legacy_cross_source_evidence(
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
    # Load source evidence profiles for credible lead classification
    profile_rows = await db.execute(select(SourceEvidenceProfile))
    profiles_by_source: dict[int, dict[str, Any]] = {}
    for p in profile_rows.scalars().all():
        profiles_by_source[p.source_id] = {
            "publisher_identity": p.publisher_identity,
            "publisher_family": p.publisher_family,
            "platform": p.platform,
            "publisher_kind": p.publisher_kind,
            "official_domains": p.official_domains or [],
        }

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
                "profile": profiles_by_source.get(content.source_id),
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

    {item["id"]: item for item in items}

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

        if len(platforms) < MIN_PLATFORMS_FOR_SIGNAL and len(source_ids) < MIN_PLATFORMS_FOR_SIGNAL:
            continue

        # Determine cross_source_level: 3+ platforms = strong, else cross_source
        if len(platforms) >= MIN_PLATFORMS_FOR_STRONG:
            level = CrossSourceLevel.STRONG_CROSS_SOURCE
        else:
            level = CrossSourceLevel.CROSS_SOURCE

        platform_list = sorted(platforms)
        independent_count = len(source_ids)

        # Persist marks for all items in the group (bidirectional)
        # Determine credible leads from source profiles
        group_families = set()
        for item in group:
            fam = (item.get("profile") or {}).get("publisher_family") or item.get("source_name") or "unknown"
            group_families.add(fam)

        has_primary = any(
            (item.get("profile") or {}).get("publisher_kind") == PublisherKind.PRIMARY
            for item in group
        )
        has_official = False
        for item in group:
            prof = item.get("profile") or {}
            domains = prof.get("official_domains") or []
            item_url = item.get("url") or ""
            if domains and any(d in item_url for d in domains):
                has_official = True
                break

        for item in group:
            mark = await repo.upsert_mark(
                content_id=item["id"],
                owner_user_id=owner_user_id,
                cross_source_level=level,
                platform_count=len(platforms),
                platforms=platform_list,
                evidence_count=len(group) - 1,
                independent_publisher_count=independent_count,
                has_primary_source=has_primary,
                has_official_source=has_official,
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

                # Determine evidence type from profile
                other_prof = other.get("profile") or {}
                other_kind = other_prof.get("publisher_kind", PublisherKind.UNKNOWN)
                if other_kind == PublisherKind.PRIMARY:
                    ev_type = EvidenceType.PRIMARY_SOURCE
                elif other_kind == PublisherKind.OFFICIAL:
                    ev_type = EvidenceType.OFFICIAL_LINK
                elif len(group_families) >= 3:
                    ev_type = EvidenceType.INDEPENDENT_REPORT
                else:
                    ev_type = EvidenceType.CROSS_SOURCE

                await repo.add_link(
                    mark_id=mark.id,
                    evidence_content_id=other["id"],
                    evidence_url=other.get("url"),
                    evidence_type=ev_type,
                    publisher_family=other_prof.get("publisher_family") or other.get("source_name"),
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


def _publisher_aliases(item: EvidenceContent) -> set[tuple[str, str]]:
    """Return every identity that can prove two sources are not independent."""

    aliases: set[tuple[str, str]] = set()
    if item.publisher_family and item.publisher_family.strip():
        aliases.add(
            ("family", item.publisher_family.strip().casefold())
        )
    if item.publisher_identity and item.publisher_identity.strip():
        aliases.add(
            ("identity", item.publisher_identity.strip().casefold())
        )
    if aliases:
        return aliases
    if item.source_id is not None:
        return {("source_id", str(item.source_id))}
    if item.source_name and item.source_name.strip():
        return {("source_name", item.source_name.strip().casefold())}
    # Missing attribution is deliberately conservative: unknown rows do not
    # manufacture independent publishers.
    return {("unknown", "unknown")}


def _event_evidence_members(event: EvidenceEvent) -> list[EvidenceContent]:
    """Choose one stable representative per independent publisher."""

    seen = {
        alias
        for alias in _publisher_aliases(event.canonical)
        if alias[0] != "unknown"
    }
    selected: list[EvidenceContent] = []
    for member in event.evidence_members:
        aliases = _publisher_aliases(member)
        known_aliases = {
            alias for alias in aliases if alias[0] != "unknown"
        }
        if not known_aliases:
            continue
        if known_aliases & seen:
            # Carry all aliases forward so identity/family equivalence closes
            # transitively across several source profiles.
            seen.update(known_aliases)
            continue
        seen.update(known_aliases)
        selected.append(member)
    return selected


def _has_known_publisher(item: EvidenceContent) -> bool:
    return any(
        alias[0] != "unknown"
        for alias in _publisher_aliases(item)
    )


def _is_official(item: EvidenceContent) -> bool:
    if item.publisher_kind == PublisherKind.OFFICIAL:
        return True
    url = (item.url or "").casefold()
    return any(
        domain.strip().casefold() in url
        for domain in item.official_domains
        if domain.strip()
    )


def _effective_time(item: EvidenceContent) -> datetime | None:
    value = item.published_at or item.crawled_at
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _time_delta_minutes(
    canonical: EvidenceContent,
    member: EvidenceContent,
) -> float | None:
    canonical_time = _effective_time(canonical)
    member_time = _effective_time(member)
    if canonical_time is None or member_time is None:
        return None
    return abs((canonical_time - member_time).total_seconds()) / 60


async def _load_event_evidence(
    db: AsyncSession,
    *,
    hours: int,
    owner_user_id: int | None,
) -> list[EvidenceEvent]:
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    return await ContentEventConsumptionRepository(db).load_active_evidence_events(
        cutoff=cutoff,
        owner_user_id=owner_user_id,
        event_limit=MAX_ITEMS_PER_RUN,
        member_limit=MAX_EVENT_EVIDENCE_MEMBERS,
    )


async def _compare_event_evidence(
    db: AsyncSession,
    *,
    hours: int,
    owner_user_id: int | None,
) -> dict[str, int]:
    events = await _load_event_evidence(
        db,
        hours=hours,
        owner_user_id=owner_user_id,
    )
    representative_count = sum(
        len(_event_evidence_members(event))
        for event in events
    )
    comparable_groups = sum(
        bool(_event_evidence_members(event))
        for event in events
    )
    return {
        "event_compare_groups": comparable_groups,
        "event_compare_members": representative_count,
        "event_compare_scanned": len(events),
    }


async def _discover_event_cross_source_evidence(
    db: AsyncSession,
    *,
    hours: int,
    owner_user_id: int | None,
) -> dict[str, int]:
    """Persist canonical-only evidence derived from active event truth."""

    events = await _load_event_evidence(
        db,
        hours=hours,
        owner_user_id=owner_user_id,
    )
    repo = EvidenceRepository(db)
    await repo.delete_noncanonical_marks_for_event_groups(
        [event.event_group_id for event in events],
        owner_user_id=owner_user_id,
    )

    total_marks = 0
    total_links = 0
    qualifying_groups = 0
    total_items = 0

    for event in events:
        selected = _event_evidence_members(event)
        total_items += 1 + len(event.evidence_members)
        canonical_known = _has_known_publisher(event.canonical)
        independent_publisher_count = len(selected) + int(canonical_known)
        platform_contributors = [
            item
            for item in (event.canonical, *selected)
            if _has_known_publisher(item)
        ]
        platforms = {
            _get_platform(item.platform or item.source_type, item.source_name)
            for item in platform_contributors
        }
        platforms.discard("unknown")
        if (
            len(platforms) < MIN_PLATFORMS_FOR_SIGNAL
            and independent_publisher_count < MIN_PLATFORMS_FOR_SIGNAL
        ):
            await repo.delete_marks_for_contents(
                [event.canonical.content_id],
                owner_user_id=owner_user_id,
            )
            continue

        qualifying_groups += 1
        level = (
            CrossSourceLevel.STRONG_CROSS_SOURCE
            if len(platforms) >= MIN_PLATFORMS_FOR_STRONG
            else CrossSourceLevel.CROSS_SOURCE
        )
        all_evidence = (event.canonical, *selected)
        mark = await repo.upsert_mark(
            content_id=event.canonical.content_id,
            owner_user_id=owner_user_id,
            cross_source_level=level,
            platform_count=len(platforms),
            platforms=sorted(platforms),
            evidence_count=len(selected),
            independent_publisher_count=independent_publisher_count,
            has_primary_source=any(
                item.publisher_kind == PublisherKind.PRIMARY
                for item in all_evidence
            ),
            has_official_source=any(_is_official(item) for item in all_evidence),
        )
        await repo.delete_links_for_mark(mark.id)

        links: list[dict[str, Any]] = []
        for member in selected:
            if member.publisher_kind == PublisherKind.PRIMARY:
                evidence_type = EvidenceType.PRIMARY_SOURCE
            elif _is_official(member):
                evidence_type = EvidenceType.OFFICIAL_LINK
            elif independent_publisher_count >= 3:
                evidence_type = EvidenceType.INDEPENDENT_REPORT
            else:
                evidence_type = EvidenceType.CROSS_SOURCE
            links.append(
                {
                    "evidence_content_id": member.content_id,
                    "evidence_url": member.url,
                    "evidence_type": evidence_type,
                    "publisher_family": (
                        member.publisher_family
                        or member.publisher_identity
                        or member.source_name
                    ),
                    "source_id": member.source_id,
                    "similarity_score": member.confidence,
                    "time_delta_minutes": _time_delta_minutes(
                        event.canonical,
                        member,
                    ),
                    "match_basis": f"event:{member.relation_type}",
                }
            )
        await repo.add_links(mark.id, links)
        total_marks += 1
        total_links += len(links)

    stats = {
        "groups": qualifying_groups,
        "marks": total_marks,
        "links": total_links,
        "total": total_items,
        "event_scanned": len(events),
    }
    logger.info(
        "Event-truth evidence: %d events → %d qualifying groups → %d marks, %d links",
        len(events),
        qualifying_groups,
        total_marks,
        total_links,
    )
    return stats
