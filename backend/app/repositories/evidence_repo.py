"""Repository for content evidence marks and links."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_event import ContentEventMember
from app.models.content_evidence import ContentEvidenceLink, ContentEvidenceMark
from app.models.evidence_interaction import EvidenceInteraction
from app.models.source import Source
from app.models.source_evidence_profile import SourceEvidenceProfile

logger = logging.getLogger(__name__)


class EvidenceRepository:
    """Batch read/write evidence marks and links."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert_mark(
        self,
        *,
        content_id: int,
        owner_user_id: int | None,
        cross_source_level: str,
        platform_count: int,
        platforms: list[str] | None,
        evidence_count: int,
        independent_publisher_count: int,
        has_primary_source: bool = False,
        has_official_source: bool = False,
    ) -> ContentEvidenceMark:
        """Insert or update a content evidence mark.

        Tolerates a lost SELECT-then-INSERT race: two concurrent upserts for the
        same (content_id, owner_user_id) can both miss the existing mark and
        both insert. The unique partial index (public scope) or
        ``uq_evidence_marks_scope`` then rejects the second insert. We isolate
        the insert in a savepoint so a collision only rolls back the savepoint,
        re-read the now-present mark, and fall through to the update path.
        """
        fields = {
            "cross_source_level": cross_source_level,
            "platform_count": platform_count,
            "platforms": platforms,
            "evidence_count": evidence_count,
            "independent_publisher_count": independent_publisher_count,
            "has_primary_source": has_primary_source,
            "has_official_source": has_official_source,
        }
        mark = await self._find_mark(content_id, owner_user_id)
        if mark is None:
            mark = ContentEvidenceMark(
                content_id=content_id,
                owner_user_id=owner_user_id,
                **fields,
            )
            try:
                async with self.db.begin_nested():
                    self.db.add(mark)
                    await self.db.flush()
            except IntegrityError:
                # A concurrent upsert won the insert race. The savepoint
                # rollback above clears the failed pending instance from the
                # session, so we simply re-read the now-persisted winning row
                # and fall through to update it with this call's values.
                mark = await self._find_mark(content_id, owner_user_id)
                if mark is None:
                    raise
        self._apply_mark_fields(mark, fields)
        await self.db.flush()
        return mark

    async def _find_mark(
        self,
        content_id: int,
        owner_user_id: int | None,
    ) -> ContentEvidenceMark | None:
        result = await self.db.execute(
            select(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id == content_id,
                ContentEvidenceMark.owner_user_id == owner_user_id,
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _apply_mark_fields(mark: ContentEvidenceMark, fields: dict[str, Any]) -> None:
        for key, value in fields.items():
            setattr(mark, key, value)
        # Recompute is a new observation. Keep computed_at accurate for
        # dashboards/audits instead of leaving a stale initial timestamp.
        mark.computed_at = datetime.now(UTC)

    async def add_link(self, mark_id: int, **kwargs: Any) -> None:
        """Add a single evidence link."""
        link = ContentEvidenceLink(mark_id=mark_id, **kwargs)
        self.db.add(link)
        await self.db.flush()

    async def add_links(self, mark_id: int, rows: list[dict[str, Any]]) -> None:
        """Add one event's bounded evidence links with a single flush."""
        if not rows:
            return
        self.db.add_all(ContentEvidenceLink(mark_id=mark_id, **values) for values in rows)
        await self.db.flush()

    async def delete_links_for_mark(self, mark_id: int) -> None:
        """Delete all links for a mark (before re-adding on recompute)."""
        await self.db.execute(delete(ContentEvidenceLink).where(ContentEvidenceLink.mark_id == mark_id))

    async def delete_marks_for_contents(
        self,
        content_ids: list[int],
        *,
        owner_user_id: int | None,
    ) -> None:
        """Delete scoped marks and their cascading links in one statement."""
        ids = sorted(set(content_ids))
        if not ids:
            return
        owner_clause = (
            ContentEvidenceMark.owner_user_id.is_(None)
            if owner_user_id is None
            else ContentEvidenceMark.owner_user_id == owner_user_id
        )
        await self.db.execute(
            delete(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id.in_(ids),
                owner_clause,
            )
        )

    async def delete_noncanonical_marks_for_event_groups(
        self,
        event_group_ids: list[int],
        *,
        owner_user_id: int | None,
    ) -> None:
        """Ensure event members never retain legacy evidence marks."""
        ids = sorted(set(event_group_ids))
        if not ids:
            return
        member_ids = select(ContentEventMember.content_id).where(ContentEventMember.event_group_id.in_(ids))
        owner_clause = (
            ContentEvidenceMark.owner_user_id.is_(None)
            if owner_user_id is None
            else ContentEvidenceMark.owner_user_id == owner_user_id
        )
        await self.db.execute(
            delete(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id.in_(member_ids),
                owner_clause,
            )
        )

    async def batch_get_marks(
        self, content_ids: list[int], owner_user_id: int | None = None
    ) -> dict[int, ContentEvidenceMark]:
        """Batch read marks for a list of content IDs (avoids N+1 in today-picks)."""
        if not content_ids:
            return {}
        result = await self.db.execute(
            select(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id.in_(content_ids),
                ContentEvidenceMark.owner_user_id == owner_user_id,
            )
        )
        return {m.content_id: m for m in result.scalars().all()}

    async def get_mark_with_links(
        self, content_id: int, owner_user_id: int | None = None
    ) -> tuple[ContentEvidenceMark | None, list[ContentEvidenceLink]]:
        """Get mark + all links for a single content item (detail page)."""
        result = await self.db.execute(
            select(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id == content_id,
                ContentEvidenceMark.owner_user_id == owner_user_id,
            )
        )
        mark = result.scalar_one_or_none()
        if not mark:
            return None, []
        link_result = await self.db.execute(select(ContentEvidenceLink).where(ContentEvidenceLink.mark_id == mark.id))
        links = list(link_result.scalars().all())
        return mark, links

    async def record_interaction(
        self,
        *,
        content_id: int,
        user_id: int | None,
        interaction_type: str,
        cross_source_level: str | None = None,
    ) -> None:
        """Record a user interaction on evidence-labeled content."""
        interaction = EvidenceInteraction(
            content_id=content_id,
            user_id=user_id,
            interaction_type=interaction_type,
            cross_source_level=cross_source_level,
        )
        self.db.add(interaction)
        await self.db.flush()

    # ── Stats methods (admin dashboard) ────────────────────────────────

    async def get_stats(self) -> dict[str, Any]:
        """Aggregated evidence statistics for admin dashboard."""
        # Marks by cross_source_level
        level_result = await self.db.execute(
            select(
                ContentEvidenceMark.cross_source_level,
                func.count(ContentEvidenceMark.id),
            ).group_by(ContentEvidenceMark.cross_source_level)
        )
        by_level: dict[str, int] = {}
        for level, cnt in level_result:
            by_level[level] = cnt

        total_marks = sum(by_level.values())

        # Credible lead counts (columns are Integer 0/1, not Boolean)
        primary_result = await self.db.execute(
            select(func.count(ContentEvidenceMark.id)).where(ContentEvidenceMark.has_primary_source == 1)
        )
        has_primary = primary_result.scalar() or 0

        official_result = await self.db.execute(
            select(func.count(ContentEvidenceMark.id)).where(ContentEvidenceMark.has_official_source == 1)
        )
        has_official = official_result.scalar() or 0

        # Links by evidence_type
        link_result = await self.db.execute(
            select(
                ContentEvidenceLink.evidence_type,
                func.count(ContentEvidenceLink.id),
            ).group_by(ContentEvidenceLink.evidence_type)
        )
        by_type: dict[str, int] = {}
        for ev_type, cnt in link_result:
            by_type[ev_type] = cnt

        total_links = sum(by_type.values())

        # Profile coverage
        total_sources_result = await self.db.execute(select(func.count(Source.id)).where(Source.scope == "system"))
        total_system_sources = total_sources_result.scalar() or 0

        profiled_result = await self.db.execute(
            select(func.count(SourceEvidenceProfile.id))
            .select_from(SourceEvidenceProfile)
            .join(Source, Source.id == SourceEvidenceProfile.source_id)
            .where(Source.scope == "system")
        )
        profiled_sources = profiled_result.scalar() or 0

        # Profiles by publisher_kind
        kind_result = await self.db.execute(
            select(
                SourceEvidenceProfile.publisher_kind,
                func.count(SourceEvidenceProfile.id),
            )
            .select_from(SourceEvidenceProfile)
            .join(Source, Source.id == SourceEvidenceProfile.source_id)
            .where(Source.scope == "system")
            .group_by(SourceEvidenceProfile.publisher_kind)
        )
        by_kind: dict[str, int] = {}
        for kind, cnt in kind_result:
            by_kind[kind] = cnt

        return {
            "marks": {
                "total": total_marks,
                "by_level": by_level,
                "has_primary_source": has_primary,
                "has_official_source": has_official,
            },
            "links": {
                "total": total_links,
                "by_type": by_type,
            },
            "profiles": {
                "total_system_sources": total_system_sources,
                "profiled_sources": profiled_sources,
                "unprofiled_sources": max(0, total_system_sources - profiled_sources),
                "by_kind": by_kind,
            },
        }

    async def get_effect_stats(self, days: int = 7) -> dict[str, Any]:
        """Compare interaction rates between evidence-marked and unmarked content.

        This is a current-state cohort comparison: public content created in
        the requested window is split by its current public evidence mark, and
        only interactions for that same content/window cohort are aggregated.

        Returns a dict with:
        - marked: {total_content, interactions_by_type, total_interactions, interaction_rate}
        - unmarked: {total_content, interactions_by_type, total_interactions, interaction_rate}
        - comparison: {click_rate_lift, favorite_rate_lift, feedback_rate_lift}
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Single, explicit cohort: public content created in the lookback
        # window. Classification uses the current public evidence mark; every
        # numerator below joins the same predicate, preventing incomparable
        # mark/content/interaction windows.
        public_mark = (
            (ContentEvidenceMark.content_id == ContentItem.id)
            & (ContentEvidenceMark.owner_user_id.is_(None))
            & (ContentEvidenceMark.cross_source_level != "none")
        )
        base_content = (
            ContentItem.owner_user_id.is_(None),
            ContentItem.created_at >= cutoff,
        )

        marked_count_result = await self.db.execute(
            select(func.count(func.distinct(ContentItem.id)))
            .select_from(ContentItem)
            .join(ContentEvidenceMark, public_mark)
            .where(*base_content)
        )
        marked_content_count = marked_count_result.scalar() or 0

        unmarked_count_result = await self.db.execute(
            select(func.count(func.distinct(ContentItem.id)))
            .select_from(ContentItem)
            .outerjoin(ContentEvidenceMark, public_mark)
            .where(*base_content, ContentEvidenceMark.id.is_(None))
        )
        unmarked_content_count = unmarked_count_result.scalar() or 0

        # Interactions on the same marked content cohort. DISTINCT protects
        # historical duplicate public mark rows from multiplying an event.
        marked_interactions_result = await self.db.execute(
            select(
                EvidenceInteraction.interaction_type,
                func.count(func.distinct(EvidenceInteraction.id)),
            )
            .select_from(EvidenceInteraction)
            .join(ContentItem, ContentItem.id == EvidenceInteraction.content_id)
            .join(ContentEvidenceMark, public_mark)
            .where(
                *base_content,
                EvidenceInteraction.created_at >= cutoff,
            )
            .group_by(EvidenceInteraction.interaction_type)
        )
        marked_by_type: dict[str, int] = {}
        marked_total_interactions = 0
        for itype, cnt in marked_interactions_result:
            marked_by_type[itype] = cnt
            marked_total_interactions += cnt

        # Interactions on the same unmarked cohort. A public mark with level
        # "none" deliberately joins as NULL and therefore belongs here.
        unmarked_interactions_result = await self.db.execute(
            select(
                EvidenceInteraction.interaction_type,
                func.count(func.distinct(EvidenceInteraction.id)),
            )
            .select_from(EvidenceInteraction)
            .join(ContentItem, ContentItem.id == EvidenceInteraction.content_id)
            .outerjoin(
                ContentEvidenceMark,
                public_mark,
            )
            .where(
                *base_content,
                ContentEvidenceMark.id.is_(None),
                EvidenceInteraction.created_at >= cutoff,
            )
            .group_by(EvidenceInteraction.interaction_type)
        )
        unmarked_by_type: dict[str, int] = {}
        unmarked_total_interactions = 0
        for itype, cnt in unmarked_interactions_result:
            unmarked_by_type[itype] = cnt
            unmarked_total_interactions += cnt

        # Compute per-type rates
        def _rate(count: int, base: int) -> float:
            return round(count / base, 4) if base > 0 else 0.0

        marked_rates = {t: _rate(c, marked_content_count) for t, c in marked_by_type.items()}
        unmarked_rates = {t: _rate(c, unmarked_content_count) for t, c in unmarked_by_type.items()}

        # Lift: how much the evidence mark improves each interaction rate
        def _lift(marked_val: float, unmarked_val: float) -> float | None:
            if unmarked_val == 0:
                return None
            return round((marked_val - unmarked_val) / unmarked_val, 4)

        all_types = set(marked_by_type) | set(unmarked_by_type)
        comparison: dict[str, float | None] = {}
        for t in all_types:
            comparison[t] = _lift(marked_rates.get(t, 0), unmarked_rates.get(t, 0))

        return {
            "window_days": days,
            "marked": {
                "total_content": marked_content_count,
                "interactions_by_type": marked_by_type,
                "total_interactions": marked_total_interactions,
                "interaction_rate": _rate(marked_total_interactions, marked_content_count),
            },
            "unmarked": {
                "total_content": unmarked_content_count,
                "interactions_by_type": unmarked_by_type,
                "total_interactions": unmarked_total_interactions,
                "interaction_rate": _rate(unmarked_total_interactions, unmarked_content_count),
            },
            "comparison": comparison,
        }
