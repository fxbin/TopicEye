"""
SourceEvidenceProfile — admin-managed source credibility profiles.

Maps each system source to a publisher identity, platform, and kind
(primary/official/publisher/aggregator/social/unknown) so the evidence
service can classify content as original publication, official link,
or independent report.

Only system sources (managed_by_admin=True) can have profiles.
User-private sources default to 'unknown' and cannot be elevated.
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PublisherKind(enum.StrEnum):
    UNKNOWN = "unknown"
    PRIMARY = "primary"
    OFFICIAL = "official"
    PUBLISHER = "publisher"
    AGGREGATOR = "aggregator"
    SOCIAL = "social"


class SourceEvidenceProfile(Base):
    """Admin-maintained credibility profile for a system source."""

    __tablename__ = "source_evidence_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=False
    )
    publisher_identity: Mapped[str] = mapped_column(String(100), nullable=False)
    publisher_family: Mapped[str] = mapped_column(String(100), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    publisher_kind: Mapped[str] = mapped_column(
        String(30), nullable=False, default=PublisherKind.UNKNOWN
    )
    official_domains: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    verification_proof_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    managed_by_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("source_id", name="uq_evidence_profile_source"),
        Index("ix_evidence_profile_identity", "publisher_identity"),
    )
