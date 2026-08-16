"""
ContentRelation — content-to-content relationship graph.

Stores typed, directional relationships between content items:
  - same_event: same news/event, different sources
  - related_topic: same topic cluster, not duplicate
  - temporal_cluster: same category within a short time window
  - causal: A is cause/background of B
  - response: B is a response/commentary on A
  - contrast: B presents an opposing viewpoint to A
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Optional

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RelationType(enum.StrEnum):
    SAME_EVENT = "same_event"
    RELATED_TOPIC = "related_topic"
    TEMPORAL_CLUSTER = "temporal_cluster"
    CAUSAL = "causal"
    RESPONSE = "response"
    CONTRAST = "contrast"


class ContentRelation(Base):
    """A typed relationship between two content items (directional)."""

    __tablename__ = "content_relations"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    source_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    target_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        UniqueConstraint("source_id", "target_id", "relation_type", name="uq_content_relations_triple"),
        Index("ix_content_relations_source", "source_id"),
        Index("ix_content_relations_target", "target_id"),
        Index("ix_content_relations_type", "relation_type"),
    )
