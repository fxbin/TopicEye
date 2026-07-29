"""Cross-source evidence derived exclusively from canonical event truth."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_evidence import CrossSourceLevel, EvidenceType
from app.models.source_evidence_profile import PublisherKind
from app.repositories.content_event_consumption_repo import (
    ContentEventConsumptionRepository,
    EvidenceContent,
    EvidenceEvent,
)
from app.repositories.evidence_repo import EvidenceRepository

logger = logging.getLogger(__name__)

MAX_ITEMS_PER_RUN = 200
MAX_EVENT_EVIDENCE_MEMBERS = 20
MIN_PLATFORMS_FOR_SIGNAL = 2
MIN_PLATFORMS_FOR_STRONG = 3


def _get_platform(source_type: str | None, source_name: str | None) -> str:
    """Normalize a source into a descriptive platform label."""

    if source_type:
        normalized = source_type.lower()
        if "rss" in normalized or "web" in normalized or "html" in normalized:
            return "website"
        return normalized
    if source_name:
        normalized = source_name.lower()
        for platform in (
            "x",
            "twitter",
            "weibo",
            "github",
            "youtube",
            "bilibili",
        ):
            if platform in normalized:
                return "x" if platform == "twitter" else platform
    return "unknown"


async def discover_cross_source_evidence(
    db: AsyncSession,
    *,
    hours: int = 24,
    owner_user_id: int | None = None,
) -> dict[str, int]:
    """Persist canonical-only evidence from accepted event relationships.

    No title/tag fallback is retained. If event-truth processing fails, the
    savepoint rolls back every partial mark/link mutation and the error
    propagates to the owning job.
    """

    async with db.begin_nested():
        return await _discover_event_cross_source_evidence(
            db,
            hours=hours,
            owner_user_id=owner_user_id,
        )


def _publisher_aliases(item: EvidenceContent) -> set[tuple[str, str]]:
    """Return every identity that can prove two sources are not independent."""

    aliases: set[tuple[str, str]] = set()
    if item.publisher_family and item.publisher_family.strip():
        aliases.add(("family", item.publisher_family.strip().casefold()))
    if item.publisher_identity and item.publisher_identity.strip():
        aliases.add(("identity", item.publisher_identity.strip().casefold()))
    if aliases:
        return aliases
    if item.source_id is not None:
        return {("source_id", str(item.source_id))}
    if item.source_name and item.source_name.strip():
        return {("source_name", item.source_name.strip().casefold())}
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
        known_aliases = {alias for alias in aliases if alias[0] != "unknown"}
        if not known_aliases:
            continue
        if known_aliases & seen:
            seen.update(known_aliases)
            continue
        seen.update(known_aliases)
        selected.append(member)
    return selected


def _has_known_publisher(item: EvidenceContent) -> bool:
    return any(alias[0] != "unknown" for alias in _publisher_aliases(item))


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


async def _discover_event_cross_source_evidence(
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
