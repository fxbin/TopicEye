"""Bounded read models for consumers of canonical content-event truth.

This repository is intentionally independent from ``content_event_repo``.
Consumer queries are batch-oriented and enforce the event owner's scope on
both the canonical and every member row.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import String, and_, case, cast, func, literal, or_, select, union_all
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventRelationType,
    EventReviewStatus,
    EventStatus,
)
from app.models.source_evidence_profile import SourceEvidenceProfile

_QUERY_BATCH_SIZE = 500
_ACCEPTED_REVIEWS = (EventReviewStatus.AUTO, EventReviewStatus.CONFIRMED)
_EVIDENCE_RELATIONS = (
    EventRelationType.CORROBORATION,
    EventRelationType.UPDATE,
)


@dataclass(frozen=True)
class EventAssignment:
    content_id: int
    event_group_id: int
    canonical_content_id: int
    is_canonical: bool
    relation_type: str | None = None
    confidence: float | None = None
    canonical_summary_source: str | None = None
    canonical_locked: bool = False
    display_is_primary: bool = False


@dataclass(frozen=True)
class EventDisplayMember:
    content_id: int
    title: str
    url: str
    source_id: int | None
    source_name: str | None
    source_type: str | None
    platform: str | None
    published_at: datetime | None
    crawled_at: datetime | None
    relation_type: str
    confidence: float
    reason: str | None


@dataclass(frozen=True)
class EventDisplayGroup:
    event_group_id: int
    canonical_content_id: int
    member_count: int
    source_count: int
    members: tuple[EventDisplayMember, ...]
    version: int = 1
    update_count: int = 0


@dataclass(frozen=True)
class EvidenceContent:
    content_id: int
    title: str
    url: str
    source_id: int | None
    source_name: str | None
    source_type: str | None
    platform: str | None
    published_at: datetime | None
    crawled_at: datetime | None
    publisher_identity: str | None
    publisher_family: str | None
    publisher_kind: str | None
    official_domains: tuple[str, ...]
    relation_type: str | None = None
    confidence: float | None = None


@dataclass(frozen=True)
class EvidenceEvent:
    event_group_id: int
    canonical: EvidenceContent
    evidence_members: tuple[EvidenceContent, ...]


def _chunks(values: Iterable[int], size: int = _QUERY_BATCH_SIZE):
    batch: list[int] = []
    for value in sorted({int(item) for item in values}):
        batch.append(value)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _visible_group_clause(visible_user_id: int | None):
    if visible_user_id is None:
        return ContentEventGroup.owner_user_id.is_(None)
    return or_(
        ContentEventGroup.owner_user_id.is_(None),
        ContentEventGroup.owner_user_id == visible_user_id,
    )


def _exact_group_owner_clause(owner_user_id: int | None):
    if owner_user_id is None:
        return ContentEventGroup.owner_user_id.is_(None)
    return ContentEventGroup.owner_user_id == owner_user_id


def _content_matches_group_owner(content_alias):
    return or_(
        and_(
            ContentEventGroup.owner_user_id.is_(None),
            content_alias.owner_user_id.is_(None),
        ),
        and_(
            ContentEventGroup.owner_user_id.is_not(None),
            content_alias.owner_user_id == ContentEventGroup.owner_user_id,
        ),
    )


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return str(getattr(value, "value", value))


def _source_key(content_alias):
    """Portable conservative source identity for aggregate source counts."""

    return func.coalesce(
        cast(content_alias.source_id, String),
        func.lower(content_alias.source_name),
        func.lower(cast(content_alias.source_type, String)),
        func.lower(content_alias.platform),
        literal("unknown"),
    )


class ContentEventConsumptionRepository:
    """Read-only, batch-bounded projections for today-picks and evidence."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def resolve_today_pick_assignments(
        self,
        content_ids: Iterable[int],
        *,
        visible_user_id: int | None,
    ) -> dict[int, EventAssignment]:
        assignments: dict[int, EventAssignment] = {}
        canonical_summary_source = (
            select(AiAnalysis.summary_source)
            .where(AiAnalysis.content_id == ContentEventGroup.canonical_content_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
            .correlate(ContentEventGroup)
            .scalar_subquery()
        )
        canonical = aliased(ContentItem)
        member_content = aliased(ContentItem)
        canonical_guard = aliased(ContentItem)
        canonical_profile = aliased(SourceEvidenceProfile)
        member_profile = aliased(SourceEvidenceProfile)

        def primary(content, profile):
            return and_(
                content.owner_user_id.is_(None),
                profile.managed_by_admin.is_(True),
                profile.reviewed_at.is_not(None),
                profile.publisher_kind.in_(("primary", "official")),
            )

        for content_batch in _chunks(content_ids):
            canonical_result = await self.db.execute(
                select(
                    ContentEventGroup.id,
                    ContentEventGroup.canonical_content_id,
                    canonical_summary_source.label("canonical_summary_source"),
                    ContentEventGroup.canonical_locked,
                    primary(canonical, canonical_profile).label("display_is_primary"),
                )
                .join(
                    canonical,
                    canonical.id == ContentEventGroup.canonical_content_id,
                )
                .where(
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(canonical),
                    ContentEventGroup.canonical_content_id.in_(content_batch),
                )
                .outerjoin(canonical_profile, canonical_profile.source_id == canonical.source_id)
            )
            for event_group_id, canonical_content_id, summary_source, locked, is_primary in canonical_result.all():
                content_id = int(canonical_content_id)
                assignments[content_id] = EventAssignment(
                    content_id=content_id,
                    event_group_id=int(event_group_id),
                    canonical_content_id=content_id,
                    is_canonical=True,
                    canonical_summary_source=summary_source,
                    canonical_locked=bool(locked),
                    display_is_primary=bool(is_primary),
                )

            member_result = await self.db.execute(
                select(
                    ContentEventGroup.id,
                    ContentEventGroup.canonical_content_id,
                    ContentEventMember.content_id,
                    ContentEventMember.relation_type,
                    ContentEventMember.confidence,
                    canonical_summary_source.label("canonical_summary_source"),
                    ContentEventGroup.canonical_locked,
                    primary(member_content, member_profile).label("display_is_primary"),
                )
                .join(
                    ContentEventMember,
                    ContentEventMember.event_group_id == ContentEventGroup.id,
                )
                .join(
                    member_content,
                    member_content.id == ContentEventMember.content_id,
                )
                .join(
                    canonical_guard,
                    canonical_guard.id == ContentEventGroup.canonical_content_id,
                )
                .where(
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(member_content),
                    _content_matches_group_owner(canonical_guard),
                    ContentEventMember.review_status.in_(_ACCEPTED_REVIEWS),
                    ContentEventMember.content_id.in_(content_batch),
                )
                .outerjoin(member_profile, member_profile.source_id == member_content.source_id)
            )
            for row in member_result.all():
                content_id = int(row[2])
                assignments[content_id] = EventAssignment(
                    content_id=content_id,
                    event_group_id=int(row[0]),
                    canonical_content_id=int(row[1]),
                    is_canonical=False,
                    relation_type=_enum_value(row[3]),
                    confidence=float(row[4]),
                    canonical_summary_source=row[5],
                    canonical_locked=bool(row[6]),
                    display_is_primary=bool(row[7]),
                )
        return assignments

    async def load_display_groups(
        self,
        event_group_ids: Iterable[int],
        *,
        visible_user_id: int | None,
        member_limit: int = 5,
        member_offset: int = 0,
        representatives: dict[int, int] | None = None,
    ) -> dict[int, EventDisplayGroup]:
        """Load other accepted reports relative to each displayed representative.

        Group identity and canonical ownership are unchanged. A non-canonical
        representative sees the original canonical in its expansion instead of
        seeing itself. Group share locks keep counts/pages on one version until
        the caller's short read transaction ends.
        """

        safe_limit = max(0, min(int(member_limit), 20))
        safe_offset = max(0, int(member_offset))
        groups: dict[int, dict[str, Any]] = {}

        for group_batch in _chunks(event_group_ids):
            canonical = aliased(ContentItem)
            canonical_result = await self.db.execute(
                select(
                    ContentEventGroup.id,
                    ContentEventGroup.canonical_content_id,
                    ContentEventGroup.version,
                )
                .join(
                    canonical,
                    canonical.id == ContentEventGroup.canonical_content_id,
                )
                .where(
                    ContentEventGroup.id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(canonical),
                )
                .order_by(ContentEventGroup.id)
                .with_for_update(read=True, of=ContentEventGroup)
            )
            for event_group_id, canonical_content_id, version in canonical_result.all():
                groups[int(event_group_id)] = {
                    "canonical_content_id": int(canonical_content_id),
                    "version": int(version),
                    "update_count": 0,
                    "member_count": 0,
                    "source_count": 1,
                    "members": [],
                }

            if not groups or safe_limit == 0:
                continue

            member_content = aliased(ContentItem)
            member_count_result = await self.db.execute(
                select(
                    ContentEventMember.event_group_id,
                    func.count(ContentEventMember.id),
                    func.sum(case((ContentEventMember.relation_type == EventRelationType.UPDATE, 1), else_=0)),
                )
                .join(
                    ContentEventGroup,
                    ContentEventGroup.id == ContentEventMember.event_group_id,
                )
                .join(
                    member_content,
                    member_content.id == ContentEventMember.content_id,
                )
                .where(
                    ContentEventMember.event_group_id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(member_content),
                    ContentEventMember.review_status.in_(_ACCEPTED_REVIEWS),
                )
                .group_by(ContentEventMember.event_group_id)
            )
            for event_group_id, member_count, update_count in member_count_result.all():
                if int(event_group_id) in groups:
                    groups[int(event_group_id)]["member_count"] = int(member_count)
                    groups[int(event_group_id)]["update_count"] = int(update_count or 0)

            canonical_source = aliased(ContentItem)
            member_source = aliased(ContentItem)
            source_rows = union_all(
                select(
                    ContentEventGroup.id.label("event_group_id"),
                    _source_key(canonical_source).label("source_key"),
                )
                .join(
                    canonical_source,
                    canonical_source.id == ContentEventGroup.canonical_content_id,
                )
                .where(
                    ContentEventGroup.id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(canonical_source),
                ),
                select(
                    ContentEventMember.event_group_id.label("event_group_id"),
                    _source_key(member_source).label("source_key"),
                )
                .join(
                    ContentEventGroup,
                    ContentEventGroup.id == ContentEventMember.event_group_id,
                )
                .join(
                    member_source,
                    member_source.id == ContentEventMember.content_id,
                )
                .where(
                    ContentEventMember.event_group_id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(member_source),
                    ContentEventMember.review_status.in_(_ACCEPTED_REVIEWS),
                ),
            ).subquery()
            source_count_result = await self.db.execute(
                select(
                    source_rows.c.event_group_id,
                    func.count(func.distinct(source_rows.c.source_key)),
                ).group_by(source_rows.c.event_group_id)
            )
            for event_group_id, source_count in source_count_result.all():
                if int(event_group_id) in groups:
                    groups[int(event_group_id)]["source_count"] = int(source_count)

            excluded_ids = [
                (representatives or {}).get(event_id, groups[event_id]["canonical_content_id"])
                for event_id in group_batch
                if event_id in groups
            ]
            ranked_content = aliased(ContentItem)
            member_rows = (
                select(
                    ContentEventMember.event_group_id.label("event_group_id"),
                    ContentEventMember.content_id.label("content_id"),
                    cast(ContentEventMember.relation_type, String).label("relation_type"),
                    ContentEventMember.confidence.label("confidence"),
                    ContentEventMember.reason.label("reason"),
                    ranked_content.title.label("title"),
                    ranked_content.url.label("url"),
                    ranked_content.source_id.label("source_id"),
                    ranked_content.source_name.label("source_name"),
                    ranked_content.source_type.label("source_type"),
                    ranked_content.platform.label("platform"),
                    ranked_content.published_at.label("published_at"),
                    ranked_content.crawled_at.label("crawled_at"),
                    func.coalesce(
                        ranked_content.published_at, ranked_content.crawled_at, ranked_content.created_at
                    ).label("sort_time"),
                )
                .join(
                    ContentEventGroup,
                    ContentEventGroup.id == ContentEventMember.event_group_id,
                )
                .join(
                    ranked_content,
                    ranked_content.id == ContentEventMember.content_id,
                )
                .where(
                    ContentEventMember.event_group_id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(ranked_content),
                    ContentEventMember.review_status.in_(_ACCEPTED_REVIEWS),
                    ranked_content.id.notin_(excluded_ids),
                )
            )
            canonical_rows = (
                select(
                    ContentEventGroup.id.label("event_group_id"),
                    canonical.id.label("content_id"),
                    literal("canonical").label("relation_type"),
                    literal(1.0).label("confidence"),
                    literal(None).label("reason"),
                    canonical.title,
                    canonical.url,
                    canonical.source_id,
                    canonical.source_name,
                    canonical.source_type,
                    canonical.platform,
                    canonical.published_at,
                    canonical.crawled_at,
                    func.coalesce(canonical.published_at, canonical.crawled_at, canonical.created_at).label(
                        "sort_time"
                    ),
                )
                .join(canonical, canonical.id == ContentEventGroup.canonical_content_id)
                .where(
                    ContentEventGroup.id.in_(group_batch),
                    ContentEventGroup.status == EventStatus.ACTIVE,
                    _visible_group_clause(visible_user_id),
                    _content_matches_group_owner(canonical),
                    canonical.id.notin_(excluded_ids),
                )
            )
            reports = union_all(member_rows, canonical_rows).subquery()
            ranked = select(
                reports,
                func.row_number()
                .over(
                    partition_by=reports.c.event_group_id,
                    order_by=(reports.c.sort_time.asc(), reports.c.content_id.asc()),
                )
                .label("member_rank"),
            ).subquery()
            member_result = await self.db.execute(
                select(ranked)
                .where(ranked.c.member_rank > safe_offset, ranked.c.member_rank <= safe_offset + safe_limit)
                .order_by(
                    ranked.c.event_group_id,
                    ranked.c.member_rank,
                    ranked.c.content_id,
                )
            )
            for row in member_result.mappings().all():
                event_group_id = int(row["event_group_id"])
                if event_group_id not in groups:
                    continue
                groups[event_group_id]["members"].append(
                    EventDisplayMember(
                        content_id=int(row["content_id"]),
                        title=row["title"] or "",
                        url=row["url"] or "",
                        source_id=row["source_id"],
                        source_name=row["source_name"],
                        source_type=_enum_value(row["source_type"]),
                        platform=row["platform"],
                        published_at=row["published_at"],
                        crawled_at=row["crawled_at"],
                        relation_type=_enum_value(row["relation_type"]) or "",
                        confidence=float(row["confidence"]),
                        reason=row["reason"],
                    )
                )

        return {
            event_group_id: EventDisplayGroup(
                event_group_id=event_group_id,
                canonical_content_id=int(values["canonical_content_id"]),
                member_count=int(values["member_count"]),
                source_count=int(values["source_count"]),
                members=tuple(values["members"]),
                version=int(values["version"]),
                update_count=int(values["update_count"]),
            )
            for event_group_id, values in groups.items()
        }

    async def load_active_evidence_events(
        self,
        *,
        cutoff: datetime,
        owner_user_id: int | None,
        event_limit: int,
        member_limit: int,
    ) -> list[EvidenceEvent]:
        """Load active event evidence with bounded groups and members."""

        safe_event_limit = max(0, min(int(event_limit), 500))
        safe_member_limit = max(0, min(int(member_limit), 50))
        if safe_event_limit == 0:
            return []

        canonical_guard = aliased(ContentItem)
        group_result = await self.db.execute(
            select(ContentEventGroup.id)
            .join(
                canonical_guard,
                canonical_guard.id == ContentEventGroup.canonical_content_id,
            )
            .where(
                ContentEventGroup.status == EventStatus.ACTIVE,
                ContentEventGroup.last_occurrence_at >= cutoff,
                _exact_group_owner_clause(owner_user_id),
                _content_matches_group_owner(canonical_guard),
            )
            .order_by(
                ContentEventGroup.last_occurrence_at.desc(),
                ContentEventGroup.id.desc(),
            )
            .limit(safe_event_limit)
        )
        group_ids = [int(value) for value in group_result.scalars().all()]
        if not group_ids:
            return []

        canonical = aliased(ContentItem)
        canonical_profile = aliased(SourceEvidenceProfile)
        canonical_result = await self.db.execute(
            select(
                ContentEventGroup.id.label("event_group_id"),
                canonical.id.label("content_id"),
                canonical.title,
                canonical.url,
                canonical.source_id,
                canonical.source_name,
                canonical.source_type,
                func.coalesce(
                    canonical_profile.platform,
                    canonical.platform,
                ).label("platform"),
                canonical.published_at,
                canonical.crawled_at,
                canonical_profile.publisher_identity,
                canonical_profile.publisher_family,
                canonical_profile.publisher_kind,
                canonical_profile.official_domains,
            )
            .join(
                canonical,
                canonical.id == ContentEventGroup.canonical_content_id,
            )
            .outerjoin(
                canonical_profile,
                canonical_profile.source_id == canonical.source_id,
            )
            .where(
                ContentEventGroup.id.in_(group_ids),
                ContentEventGroup.status == EventStatus.ACTIVE,
                _exact_group_owner_clause(owner_user_id),
                _content_matches_group_owner(canonical),
            )
        )
        canonicals: dict[int, EvidenceContent] = {}
        for row in canonical_result.mappings().all():
            canonicals[int(row["event_group_id"])] = _evidence_content_from_row(row)

        if safe_member_limit == 0:
            return [
                EvidenceEvent(
                    event_group_id=event_group_id,
                    canonical=canonicals[event_group_id],
                    evidence_members=(),
                )
                for event_group_id in group_ids
                if event_group_id in canonicals
            ]

        member_content = aliased(ContentItem)
        member_profile = aliased(SourceEvidenceProfile)
        ranked = (
            select(
                ContentEventMember.event_group_id.label("event_group_id"),
                ContentEventMember.content_id.label("content_id"),
                ContentEventMember.relation_type.label("relation_type"),
                ContentEventMember.confidence.label("confidence"),
                member_content.title.label("title"),
                member_content.url.label("url"),
                member_content.source_id.label("source_id"),
                member_content.source_name.label("source_name"),
                member_content.source_type.label("source_type"),
                func.coalesce(
                    member_profile.platform,
                    member_content.platform,
                ).label("platform"),
                member_content.published_at.label("published_at"),
                member_content.crawled_at.label("crawled_at"),
                member_profile.publisher_identity.label("publisher_identity"),
                member_profile.publisher_family.label("publisher_family"),
                member_profile.publisher_kind.label("publisher_kind"),
                member_profile.official_domains.label("official_domains"),
                func.row_number()
                .over(
                    partition_by=ContentEventMember.event_group_id,
                    order_by=(
                        func.coalesce(
                            member_content.published_at,
                            member_content.crawled_at,
                            member_content.created_at,
                        ).asc(),
                        member_content.id.asc(),
                    ),
                )
                .label("member_rank"),
            )
            .join(
                ContentEventGroup,
                ContentEventGroup.id == ContentEventMember.event_group_id,
            )
            .join(
                member_content,
                member_content.id == ContentEventMember.content_id,
            )
            .outerjoin(
                member_profile,
                member_profile.source_id == member_content.source_id,
            )
            .where(
                ContentEventMember.event_group_id.in_(group_ids),
                ContentEventGroup.status == EventStatus.ACTIVE,
                _exact_group_owner_clause(owner_user_id),
                _content_matches_group_owner(member_content),
                ContentEventMember.review_status.in_(_ACCEPTED_REVIEWS),
                ContentEventMember.relation_type.in_(_EVIDENCE_RELATIONS),
            )
            .subquery()
        )
        member_result = await self.db.execute(
            select(ranked)
            .where(ranked.c.member_rank <= safe_member_limit)
            .order_by(
                ranked.c.event_group_id,
                ranked.c.member_rank,
                ranked.c.content_id,
            )
        )
        members: dict[int, list[EvidenceContent]] = {event_group_id: [] for event_group_id in group_ids}
        for row in member_result.mappings().all():
            event_group_id = int(row["event_group_id"])
            if event_group_id in members:
                members[event_group_id].append(_evidence_content_from_row(row))

        return [
            EvidenceEvent(
                event_group_id=event_group_id,
                canonical=canonicals[event_group_id],
                evidence_members=tuple(members[event_group_id]),
            )
            for event_group_id in group_ids
            if event_group_id in canonicals
        ]


def _evidence_content_from_row(row) -> EvidenceContent:
    domains = row["official_domains"] or ()
    return EvidenceContent(
        content_id=int(row["content_id"]),
        title=row["title"] or "",
        url=row["url"] or "",
        source_id=row["source_id"],
        source_name=row["source_name"],
        source_type=_enum_value(row["source_type"]),
        platform=row["platform"],
        published_at=row["published_at"],
        crawled_at=row["crawled_at"],
        publisher_identity=row["publisher_identity"],
        publisher_family=row["publisher_family"],
        publisher_kind=_enum_value(row["publisher_kind"]),
        official_domains=tuple(str(value) for value in domains),
        relation_type=_enum_value(row.get("relation_type")),
        confidence=(float(row["confidence"]) if row.get("confidence") is not None else None),
    )
