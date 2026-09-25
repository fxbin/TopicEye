from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content_label import (
    ContentLabel,
    ContentLabelSource,
    ContentLabelValue,
)

# 人工来源（不可被行为刷新覆盖）
_AUTHORITATIVE_SOURCES = (ContentLabelSource.HUMAN.value, ContentLabelSource.PICK_MARK.value)


class ContentLabelRepository:
    """内容标注的唯一 ORM 入口。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_behavioral(
        self,
        content_id: int,
        label: str,
        confidence: float,
        evidence: dict,
    ) -> None:
        """写入/更新行为弱标注；已有人工或 pick_mark 标注的行不动。"""
        existing = await self.get_by_content_id(content_id)
        if existing is not None and existing.source in _AUTHORITATIVE_SOURCES:
            return
        if existing is not None:
            existing.label = label
            existing.confidence = confidence
            existing.evidence = evidence
            existing.source = ContentLabelSource.BEHAVIORAL.value
            existing.updated_at = datetime.now(UTC)
            await self.db.flush()
            return
        self.db.add(
            ContentLabel(
                content_id=content_id,
                label=label,
                source=ContentLabelSource.BEHAVIORAL.value,
                confidence=confidence,
                evidence=evidence,
            )
        )
        await self.db.flush()

    async def drop_behavioral(self, content_id: int) -> None:
        """证据不足以推断结论时，清掉过期的行为标注（不动人工行）。"""
        existing = await self.get_by_content_id(content_id)
        if existing is not None and existing.source == ContentLabelSource.BEHAVIORAL.value:
            await self.db.execute(delete(ContentLabel).where(ContentLabel.id == existing.id))
            await self.db.flush()

    async def set_authoritative(
        self,
        content_id: int,
        label: str,
        *,
        source: str,
        labeled_by: int | None = None,
        confidence: float = 1.0,
        evidence: dict | None = None,
    ) -> ContentLabel:
        """写入人工 / pick_mark 标注（覆盖行为行，被同类来源覆盖更新）。"""
        if source not in _AUTHORITATIVE_SOURCES:
            raise ValueError(f"source must be one of {_AUTHORITATIVE_SOURCES}, got {source}")
        if label not in {v.value for v in ContentLabelValue}:
            raise ValueError(f"unknown label: {label}")
        stmt = (
            pg_insert(ContentLabel)
            .values(
                content_id=content_id,
                label=label,
                source=source,
                labeled_by=labeled_by,
                confidence=confidence,
                evidence=evidence,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                index_elements=["content_id"],
                set_={
                    "label": label,
                    "source": source,
                    "labeled_by": labeled_by,
                    "confidence": confidence,
                    "evidence": evidence,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(ContentLabel)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.scalar_one()

    async def get_by_content_id(self, content_id: int) -> ContentLabel | None:
        result = await self.db.execute(select(ContentLabel).where(ContentLabel.content_id == content_id))
        return result.scalar_one_or_none()

    async def list_with_titles(
        self,
        *,
        source: str | None = None,
        limit: int = 50,
    ) -> list[tuple[ContentLabel, str]]:
        """最近更新的标注（附内容标题），供管理端列表展示。"""
        from app.models.content import ContentItem

        stmt = (
            select(ContentLabel, ContentItem.title)
            .join(ContentItem, ContentItem.id == ContentLabel.content_id)
            .order_by(ContentLabel.updated_at.desc())
            .limit(limit)
        )
        if source:
            stmt = stmt.where(ContentLabel.source == source)
        result = await self.db.execute(stmt)
        return list(result.all())

    async def get_label_map(self, content_ids: Sequence[int]) -> dict[int, ContentLabel]:
        if not content_ids:
            return {}
        result = await self.db.execute(select(ContentLabel).where(ContentLabel.content_id.in_(content_ids)))
        return {row.content_id: row for row in result.scalars().all()}
