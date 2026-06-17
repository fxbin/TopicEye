"""
Repository for DailyReport — daily briefing queries.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from collections.abc import Sequence

from sqlalchemy import select

from app.models.daily_report import DailyReport
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DailyReportRepository(BaseRepository[DailyReport]):
    """DailyReport repository with date-based lookups."""

    model = DailyReport

    async def get_by_date(
        self,
        report_date: str,
        edition: str | None = None,
        owner_user_id: int | None = None,
    ) -> DailyReport | None:
        """Fetch final report for a date, or latest snapshot if final does not exist.

        ``owner_user_id``: ``None`` → public (NULL) reports; ``int`` → strictly
        match a user-owned report. Pass the user's id for the /me endpoints;
        pass ``None`` for the public endpoints.
        """
        if edition:
            stmt = (
                select(self.model)
                .where(self.model.report_date == report_date)
                .where(self.model.edition == edition)
                .where(self.model.owner_user_id.is_(owner_user_id))
                .order_by(self.model.cutoff_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()

        final_stmt = (
            select(self.model)
            .where(self.model.report_date == report_date)
            .where(self.model.edition == "final")
            .where(self.model.owner_user_id.is_(owner_user_id))
            .order_by(self.model.cutoff_at.desc())
            .limit(1)
        )
        final_result = await self.db.execute(final_stmt)
        final_report = final_result.scalar_one_or_none()
        if final_report:
            return final_report

        stmt = (
            select(self.model)
            .where(self.model.report_date == report_date)
            .where(self.model.owner_user_id.is_(owner_user_id))
            .order_by(self.model.cutoff_at.desc(), self.model.updated_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_latest(
        self,
        limit: int = 7,
        owner_user_id: int | None = None,
    ) -> Sequence[DailyReport]:
        """Return the most recent reports, newest first.

        ``owner_user_id``: ``None`` → public reports; ``int`` → strictly match
        a user-owned report. Pass the user's id for the /me endpoints.
        """
        stmt = (
            select(self.model)
            .where(self.model.owner_user_id.is_(owner_user_id))
            .order_by(self.model.report_date.desc(), self.model.cutoff_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_dates_with_reports(
        self,
        owner_user_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return latest report version per date, newest first.

        ``owner_user_id``: ``None`` → public dates; ``int`` → only the user's
        own report dates. Pass the user's id for the /me endpoints.
        """
        stmt = (
            select(
                self.model.report_date,
                self.model.weekday,
                self.model.takeaway,
                self.model.status,
                self.model.edition,
                self.model.generated_at,
                self.model.cutoff_at,
            )
            .where(self.model.owner_user_id.is_(owner_user_id))
            .order_by(self.model.report_date.desc(), self.model.cutoff_at.desc())
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        seen: set[str] = set()
        dates: list[dict[str, Any]] = []
        for row in rows:
            if row[0] in seen:
                continue
            seen.add(row[0])
            dates.append(
                {
                    "report_date": row[0],
                    "weekday": row[1],
                    "takeaway": row[2][:60] if row[2] else None,
                    "status": row[3],
                    "edition": row[4],
                    "generated_at": row[5],
                    "cutoff_at": row[6],
                }
            )
        return dates
