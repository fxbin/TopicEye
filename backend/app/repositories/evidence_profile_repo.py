"""Repository for source evidence profiles."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source_evidence_profile import PublisherKind, SourceEvidenceProfile


class SourceEvidenceProfileRepository:
    """CRUD for source evidence profiles (admin-managed credible lead config)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_by_source_id(self, source_id: int) -> SourceEvidenceProfile | None:
        result = await self.db.execute(
            select(SourceEvidenceProfile).where(SourceEvidenceProfile.source_id == source_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        source_id: int,
        publisher_identity: str,
        publisher_family: str,
        platform: str,
        publisher_kind: str = PublisherKind.UNKNOWN,
        official_domains: list[str] | None = None,
        verification_proof_url: str | None = None,
    ) -> SourceEvidenceProfile:
        profile = await self.get_by_source_id(source_id)
        now = datetime.now(UTC)

        if profile:
            profile.publisher_identity = publisher_identity
            profile.publisher_family = publisher_family
            profile.platform = platform
            profile.publisher_kind = publisher_kind
            profile.official_domains = official_domains
            profile.verification_proof_url = verification_proof_url
            profile.reviewed_at = now
            profile.updated_at = now
        else:
            profile = SourceEvidenceProfile(
                source_id=source_id,
                publisher_identity=publisher_identity,
                publisher_family=publisher_family,
                platform=platform,
                publisher_kind=publisher_kind,
                official_domains=official_domains,
                verification_proof_url=verification_proof_url,
                reviewed_at=now,
            )
            self.db.add(profile)
        await self.db.flush()
        return profile
