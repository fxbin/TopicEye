"""Repository for content evidence marks and links."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_evidence import ContentEvidenceLink, ContentEvidenceMark
from app.models.evidence_interaction import EvidenceInteraction

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
