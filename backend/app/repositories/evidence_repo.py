"""Repository for content evidence marks and links."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
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
        """Insert or update a content evidence mark."""
        result = await self.db.execute(
            select(ContentEvidenceMark).where(
                ContentEvidenceMark.content_id == content_id,
                ContentEvidenceMark.owner_user_id == owner_user_id,
            )
        )
        mark = result.scalar_one_or_none()
        if mark:
            mark.cross_source_level = cross_source_level
            mark.platform_count = platform_count
            mark.platforms = platforms
            mark.evidence_count = evidence_count
            mark.independent_publisher_count = independent_publisher_count
            mark.has_primary_source = has_primary_source
            mark.has_official_source = has_official_source
        else:
            mark = ContentEvidenceMark(
                content_id=content_id,
                owner_user_id=owner_user_id,
                cross_source_level=cross_source_level,
                platform_count=platform_count,
                platforms=platforms,
                evidence_count=evidence_count,
                independent_publisher_count=independent_publisher_count,
                has_primary_source=has_primary_source,
                has_official_source=has_official_source,
            )
            self.db.add(mark)
        await self.db.flush()
        return mark

    async def add_link(self, mark_id: int, **kwargs: Any) -> None:
        """Add a single evidence link."""
        link = ContentEvidenceLink(mark_id=mark_id, **kwargs)
        self.db.add(link)
        await self.db.flush()

    async def delete_links_for_mark(self, mark_id: int) -> None:
        """Delete all links for a mark (before re-adding on recompute)."""
        await self.db.execute(
            delete(ContentEvidenceLink).where(ContentEvidenceLink.mark_id == mark_id)
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
        link_result = await self.db.execute(
            select(ContentEvidenceLink).where(ContentEvidenceLink.mark_id == mark.id)
        )
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
            select(func.count(ContentEvidenceMark.id)).where(
                ContentEvidenceMark.has_primary_source == 1
            )
        )
        has_primary = primary_result.scalar() or 0

        official_result = await self.db.execute(
            select(func.count(ContentEvidenceMark.id)).where(
                ContentEvidenceMark.has_official_source == 1
            )
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
        total_sources_result = await self.db.execute(
            select(func.count(Source.id)).where(Source.scope == "system")
        )
        total_system_sources = total_sources_result.scalar() or 0

        profiled_result = await self.db.execute(
            select(func.count(SourceEvidenceProfile.id))
        )
        profiled_sources = profiled_result.scalar() or 0

        # Profiles by publisher_kind
        kind_result = await self.db.execute(
            select(
                SourceEvidenceProfile.publisher_kind,
                func.count(SourceEvidenceProfile.id),
            ).group_by(SourceEvidenceProfile.publisher_kind)
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
                "unprofiled_sources": total_system_sources - profiled_sources,
                "by_kind": by_kind,
            },
        }

    async def get_effect_stats(self, days: int = 7) -> dict[str, Any]:
        """Compare interaction rates between evidence-marked and unmarked content.

        This is the effect validation query. It joins content_items
        with evidence_marks (LEFT JOIN, so unmarked content is included) and
        aggregates interaction counts per group.

        Returns a dict with:
        - marked: {total_content, interactions_by_type, total_interactions, interaction_rate}
        - unmarked: {total_content, interactions_by_type, total_interactions, interaction_rate}
        - comparison: {click_rate_lift, favorite_rate_lift, feedback_rate_lift}
        """
        from datetime import UTC, datetime, timedelta

        cutoff = datetime.now(UTC) - timedelta(days=days)

        # Count content items with and without evidence marks (public scope only)
        marked_count_result = await self.db.execute(
            select(func.count(ContentEvidenceMark.id)).where(
                ContentEvidenceMark.owner_user_id.is_(None),
                ContentEvidenceMark.cross_source_level != "none",
                ContentEvidenceMark.computed_at >= cutoff,
            )
        )
        marked_content_count = marked_count_result.scalar() or 0

        # Total public content in the window
        total_content_result = await self.db.execute(
            select(func.count(ContentItem.id)).where(
                ContentItem.owner_user_id.is_(None),
                ContentItem.created_at >= cutoff,
            )
        )
        total_content = total_content_result.scalar() or 0
        unmarked_content_count = max(0, total_content - marked_content_count)

        # Interactions on marked content
        marked_interactions_result = await self.db.execute(
            select(
                EvidenceInteraction.interaction_type,
                func.count(EvidenceInteraction.id),
            )
            .select_from(EvidenceInteraction)
            .join(ContentEvidenceMark, ContentEvidenceMark.content_id == EvidenceInteraction.content_id)
            .where(
                ContentEvidenceMark.owner_user_id.is_(None),
                ContentEvidenceMark.cross_source_level != "none",
                EvidenceInteraction.created_at >= cutoff,
            )
            .group_by(EvidenceInteraction.interaction_type)
        )
        marked_by_type: dict[str, int] = {}
        marked_total_interactions = 0
        for itype, cnt in marked_interactions_result:
            marked_by_type[itype] = cnt
            marked_total_interactions += cnt

        # Interactions on unmarked content (content_id NOT in evidence_marks)
        unmarked_interactions_result = await self.db.execute(
            select(
                EvidenceInteraction.interaction_type,
                func.count(EvidenceInteraction.id),
            )
            .select_from(EvidenceInteraction)
            .outerjoin(
                ContentEvidenceMark,
                (ContentEvidenceMark.content_id == EvidenceInteraction.content_id)
                & (ContentEvidenceMark.owner_user_id.is_(None)),
            )
            .where(
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
