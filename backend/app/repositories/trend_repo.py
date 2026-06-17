"""
Repository for TopicTrend — daily snapshot CRUD + range queries.
"""

from __future__ import annotations

import logging
from datetime import date
from collections.abc import Sequence

from sqlalchemy import delete, select

from app.models.trend import TopicTrend
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
        stmt = delete(self.model).where(self.model.snapshot_date == target_date)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount
