"""
Repository for ContentRelation — CRUD + query helpers.

Follows the layering rule: this is the only module that writes
ORM queries against the content_relations table.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.content_relation import ContentRelation


class RelationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def upsert_relation(
        self,
        *,
        source_id: int,
        target_id: int,
        relation_type: str,
        confidence: float,
        evidence: str | None = None,
    ) -> ContentRelation:
        """Insert or update a relation (upsert on (source, target, type))."""
        existing = await self.db.execute(
            select(ContentRelation).where(
                ContentRelation.source_id == source_id,
                ContentRelation.target_id == target_id,
                ContentRelation.relation_type == relation_type,
            )
        )
        record = existing.scalar_one_or_none()
        if record:
            record.confidence = confidence
            record.evidence = evidence
        else:
            record = ContentRelation(
                source_id=source_id,
                target_id=target_id,
                relation_type=relation_type,
                confidence=confidence,
                evidence=evidence,
            )
            self.db.add(record)
        await self.db.flush()
        return record

    async def list_relations_for_content(self, content_id: int, *, limit: int = 20) -> list[dict[str, Any]]:
        """Return all relations involving content_id (as source or target)."""
        result = await self.db.execute(
            select(ContentRelation, ContentItem)
            .join(ContentItem, ContentItem.id == ContentRelation.target_id)
            .where(ContentRelation.source_id == content_id)
            .order_by(ContentRelation.confidence.desc())
            .limit(limit)
        )
        rows = result.all()
        out: list[dict[str, Any]] = []
        for relation, target in rows:
            out.append(
                {
                    "relation_id": relation.id,
                    "source_id": relation.source_id,
                    "target_id": relation.target_id,
                    "relation_type": relation.relation_type,
                    "confidence": relation.confidence,
                    "evidence": relation.evidence,
                    "target_title": target.title,
                    "target_source_name": target.source_name,
                    "target_category": target.category,
                    "target_crawled_at": target.crawled_at.isoformat() if target.crawled_at else None,
                }
            )
        return out

    async def delete_all_for_content(self, content_id: int) -> int:
        """Delete all relations where content_id is source or target."""
        result = await self.db.execute(
            delete(ContentRelation).where(
                (ContentRelation.source_id == content_id) | (ContentRelation.target_id == content_id)
            )
        )
        return result.rowcount
