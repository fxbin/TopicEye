"""
Repository for WeeklyDigest — weekly newsletter queries.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.weekly_digest import WeeklyDigest
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class WeeklyDigestRepository(BaseRepository[WeeklyDigest]):
    """WeeklyDigest repository with week-based lookups.

    所有周报相关的 ORM 查询都集中在这里，api 层只调用、不直接写 sqlalchemy。
    """

    model = WeeklyDigest

    async def get_by_week_key(self, week_key: str) -> WeeklyDigest | None:
        """Fetch a single digest by its week key (e.g. '2025-W21')."""
        stmt = select(self.model).where(self.model.week_key == week_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest(self, limit: int = 8) -> Sequence[WeeklyDigest]:
        """Return the most recent weekly digests, newest first."""
        stmt = select(self.model).order_by(self.model.week_start.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_weeks_with_digests(self) -> list[dict[str, str | None]]:
        """Return list of {week_key, week_label, takeaway, status} for all digests, newest first."""
        stmt = select(
            self.model.week_key,
            self.model.week_label,
            self.model.takeaway,
            self.model.status,
        ).order_by(self.model.week_start.desc())
        result = await self.db.execute(stmt)
        rows = result.all()
        return [
            {
                "week_key": row[0],
                "week_label": row[1],
                "takeaway": row[2][:80] if row[2] else None,
                "status": row[3],
            }
            for row in rows
        ]

    async def count_all(self) -> int:
        """统计周报总记录数，供 /weekly-digests 列表端点返回 total 字段使用。"""
        result = await self.db.execute(select(func.count()).select_from(self.model))
        return result.scalar() or 0
