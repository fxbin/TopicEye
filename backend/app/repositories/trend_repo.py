"""
Repository for TopicTrend — daily snapshot CRUD + range queries.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import date
from typing import Literal

from sqlalchemy import String, and_, case, cast, delete, func, or_, select

from app.models.content import ContentItem
from app.models.content_evidence import ContentEvidenceMark
from app.models.trend import TopicTrend, TopicTrendMember
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class TrendRepository(BaseRepository[TopicTrend]):
    """TopicTrend repository with date-range and deletion helpers."""

    model = TopicTrend

    async def get_by_date_range(
        self,
        start: date,
        end: date,
    ) -> Sequence[TopicTrend]:
        """Return all trend snapshots whose snapshot_date falls in [start, end]."""
        stmt = (
            select(self.model)
            .where(self.model.snapshot_date >= start)
            .where(self.model.snapshot_date <= end)
            .order_by(self.model.snapshot_date.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def delete_by_date(self, target_date: date) -> int:
        """Delete all trend snapshots for *target_date*. Returns count deleted."""
        trend_ids = select(self.model.id).where(self.model.snapshot_date == target_date)
        # Delete explicitly before the parent.  Production foreign keys also
        # cascade this, but explicit deletion keeps replacement idempotent in
        # SQLite test engines that were created without PRAGMA foreign_keys.
        await self.db.execute(delete(TopicTrendMember).where(TopicTrendMember.trend_id.in_(trend_ids)))
        stmt = delete(self.model).where(self.model.snapshot_date == target_date)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount

    async def add_snapshot_with_members(
        self,
        snapshot: TopicTrend,
        member_values: list[dict],
        *,
        batch_size: int = 500,
    ) -> TopicTrend:
        """Persist one aggregate and its frozen members without per-row flushes."""
        self.db.add(snapshot)
        await self.db.flush()

        for start in range(0, len(member_values), batch_size):
            batch = member_values[start : start + batch_size]
            self.db.add_all([TopicTrendMember(trend_id=snapshot.id, **values) for values in batch])
        return snapshot

    async def count_members(self, trend_id: int) -> int:
        result = await self.db.execute(
            select(func.count(TopicTrendMember.id)).where(TopicTrendMember.trend_id == trend_id)
        )
        return int(result.scalar_one())

    async def get_topic_snapshot(self, topic_id: int, snapshot_date: date) -> TopicTrend | None:
        result = await self.db.execute(
            select(TopicTrend).where(
                TopicTrend.topic_id == topic_id,
                TopicTrend.snapshot_date == snapshot_date,
            )
        )
        return result.scalar_one_or_none()

    async def get_keyword_snapshots(self, keyword: str, start: date, end: date) -> Sequence[TopicTrend]:
        result = await self.db.execute(
            select(TopicTrend)
            .where(
                TopicTrend.keyword == keyword,
                TopicTrend.snapshot_date >= start,
                TopicTrend.snapshot_date <= end,
            )
            .order_by(TopicTrend.snapshot_date.desc(), TopicTrend.id.desc())
        )
        return result.scalars().all()

    @staticmethod
    def _visible_public_member_clause():
        """Allow deleted content snapshots, but never expose now-private content."""
        return or_(
            TopicTrendMember.content_id.is_(None),
            ContentItem.owner_user_id.is_(None),
        )

    @staticmethod
    def _evidence_predicate():
        return or_(
            ContentEvidenceMark.evidence_count > 0,
            ContentEvidenceMark.has_primary_source == 1,
            ContentEvidenceMark.has_official_source == 1,
            ContentEvidenceMark.cross_source_level != "none",
        )

    def _member_statement(
        self,
        trend_ids: list[int],
        evidence_filter: Literal["all", "selected", "evidenced"],
    ):
        stmt = (
            select(TopicTrendMember, ContentEvidenceMark)
            .outerjoin(ContentItem, ContentItem.id == TopicTrendMember.content_id)
            .outerjoin(
                ContentEvidenceMark,
                and_(
                    ContentEvidenceMark.content_id == TopicTrendMember.content_id,
                    ContentEvidenceMark.owner_user_id.is_(None),
                ),
            )
            .where(
                TopicTrendMember.trend_id.in_(trend_ids),
                self._visible_public_member_clause(),
            )
        )
        if evidence_filter == "selected":
            stmt = stmt.where(TopicTrendMember.selected.is_(True))
        elif evidence_filter == "evidenced":
            stmt = stmt.where(self._evidence_predicate())
        return stmt

    async def summarize_members(self, trend_ids: list[int]) -> dict[str, int]:
        """Return public member totals for a snapshot scope in one aggregate query."""
        if not trend_ids:
            return {"content_count": 0, "source_count": 0, "selected_count": 0, "evidenced_count": 0}
        stmt = (
            select(
                func.count(TopicTrendMember.id).label("content_count"),
                func.count(
                    func.distinct(
                        func.coalesce(
                            cast(TopicTrendMember.source_id_snapshot, String),
                            TopicTrendMember.source_name_snapshot,
                        )
                    )
                ).label("source_count"),
                func.coalesce(func.sum(case((TopicTrendMember.selected.is_(True), 1), else_=0)), 0).label(
                    "selected_count"
                ),
                func.coalesce(func.sum(case((self._evidence_predicate(), 1), else_=0)), 0).label("evidenced_count"),
            )
            .select_from(TopicTrendMember)
            .outerjoin(ContentItem, ContentItem.id == TopicTrendMember.content_id)
            .outerjoin(
                ContentEvidenceMark,
                and_(
                    ContentEvidenceMark.content_id == TopicTrendMember.content_id,
                    ContentEvidenceMark.owner_user_id.is_(None),
                ),
            )
            .where(
                TopicTrendMember.trend_id.in_(trend_ids),
                self._visible_public_member_clause(),
            )
        )
        row = (await self.db.execute(stmt)).one()
        return {
            "content_count": int(row.content_count or 0),
            "source_count": int(row.source_count or 0),
            "selected_count": int(row.selected_count or 0),
            "evidenced_count": int(row.evidenced_count or 0),
        }

    async def list_members(
        self,
        trend_ids: list[int],
        *,
        evidence_filter: Literal["all", "selected", "evidenced"],
        page: int,
        page_size: int,
        keyword_order: bool = False,
    ) -> tuple[Sequence[tuple[TopicTrendMember, ContentEvidenceMark | None]], int]:
        """Read a public page of members and their public marks with no N+1 query."""
        if not trend_ids:
            return [], 0
        stmt = self._member_statement(trend_ids, evidence_filter)
        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int((await self.db.execute(total_stmt)).scalar_one())

        if keyword_order:
            stmt = stmt.order_by(
                func.coalesce(
                    TopicTrendMember.published_at_snapshot,
                    TopicTrendMember.crawled_at_snapshot,
                ).desc(),
                TopicTrendMember.position,
            )
        else:
            stmt = stmt.order_by(TopicTrendMember.position)
        stmt = stmt.offset((page - 1) * page_size).limit(page_size)
        rows = (await self.db.execute(stmt)).all()
        return rows, total
