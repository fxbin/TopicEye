"""
Repository for MonthlyDigest — monthly newsletter queries.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select

from app.models.monthly_digest import MonthlyDigest
from app.repositories.base import BaseRepository


class MonthlyDigestRepository(BaseRepository[MonthlyDigest]):
    """MonthlyDigest repository with month-based lookups."""

    model = MonthlyDigest

    async def get_by_month_key(self, month_key: str) -> MonthlyDigest | None:
        stmt = select(self.model).where(self.model.month_key == month_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest(self, limit: int = 12) -> Sequence[MonthlyDigest]:
        stmt = select(self.model).order_by(self.model.month_start.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        """返回 MonthlyDigest 总条数，供列表端点返回 total 字段使用。"""
        stmt = select(func.count()).select_from(self.model)
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def get_months_with_digests(self) -> list[dict[str, str | None]]:
        stmt = select(
            self.model.month_key,
            self.model.month_label,
            self.model.takeaway,
            self.model.status,
        ).order_by(self.model.month_start.desc())
        result = await self.db.execute(stmt)
        return [
            {
                "month_key": row[0],
                "month_label": row[1],
                "takeaway": row[2][:80] if row[2] else None,
                "status": row[3],
            }
            for row in result.all()
        ]
