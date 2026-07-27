"""
Repository for DailyReport — daily briefing queries.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any

from sqlalchemy import func, select

from app.models.daily_report import DailyReport
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class DailyReportRepository(BaseRepository[DailyReport]):
    """DailyReport repository with date-based lookups.

    所有日报相关的 ORM 查询都集中在这里，api 层只调用、不直接写 sqlalchemy。
    """

    model = DailyReport

    def _owner_clause(self, owner_user_id: int | None):
        """构建归属过滤子句（Postgres 安全）。

        ``owner_user_id`` 为 ``None`` → 公共日报（``owner_user_id IS NULL``）；
        为 ``int`` → 严格匹配该用户私有日报（``owner_user_id == <int>``）。

        注意：不能用 ``.is_(owner_user_id)`` 传 int —— Postgres 的 ``IS`` 操作符
        只接受 NULL/TRUE/FALSE，传整数会报 syntax error（SQLite 容忍，Postgres 不容忍）。
        这是 daily_reports 旧代码的潜在 bug，本仓库逐步迁移到此 helper。
        """
        if owner_user_id is None:
            return self.model.owner_user_id.is_(None)
        return self.model.owner_user_id == owner_user_id

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
                .where(self._owner_clause(owner_user_id))
                .order_by(self.model.cutoff_at.desc())
                .limit(1)
            )
            result = await self.db.execute(stmt)
            return result.scalar_one_or_none()

        final_stmt = (
            select(self.model)
            .where(self.model.report_date == report_date)
            .where(self.model.edition == "final")
            .where(self._owner_clause(owner_user_id))
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
            .where(self._owner_clause(owner_user_id))
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
            .where(self._owner_clause(owner_user_id))
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
            .where(self._owner_clause(owner_user_id))
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

    async def list_for_calendar(
        self,
        start_iso: str,
        end_iso: str,
    ) -> Sequence[DailyReport]:
        """按日期范围查询日报（含所有 edition），供 /calendar 端点分组聚合使用。

        排序：report_date DESC, cutoff_at DESC, updated_at DESC（与历史行为等价）。
        """
        stmt = (
            select(self.model)
            .where(self.model.report_date >= start_iso)
            .where(self.model.report_date <= end_iso)
            .order_by(
                self.model.report_date.desc(),
                self.model.cutoff_at.desc(),
                self.model.updated_at.desc(),
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_all(self) -> int:
        """统计日报总记录数，供 /daily-reports 端点返回 total 字段使用。"""
        result = await self.db.execute(select(func.count()).select_from(self.model))
        return result.scalar() or 0

    async def list_recent_with_limit(self, limit: int = 7) -> Sequence[DailyReport]:
        """返回最近的 N 条日报（所有 edition），按 report_date 和 cutoff_at 倒序。"""
        stmt = (
            select(self.model)
            .order_by(self.model.report_date.desc(), self.model.cutoff_at.desc())
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def find_existing_for_version(
        self,
        report_date_iso: str,
        edition: str,
        owner_user_id: int | None = None,
    ) -> DailyReport | None:
        """按 (date, edition, owner) 查现有日报记录（取最新一条），供生成版本端点判断使用。

        取最新一条是为了避免历史脏数据导致 MultipleResultsFound。
        """
        stmt = (
            select(self.model)
            .where(
                self.model.report_date == report_date_iso,
                self.model.edition == edition,
                self._owner_clause(owner_user_id),
            )
            .order_by(self.model.id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, report_id: int) -> DailyReport | None:
        """按主键查日报记录。供后台生成失败时定位记录使用。"""
        stmt = select(self.model).where(self.model.id == report_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_yesterday_report(
        self,
        report_date: str,
        owner_user_id: int | None = None,
    ) -> DailyReport | None:
        """取指定日期的「昨日」报告，供昨日追踪卡用。

        口径与 ``get_by_date`` 一致：``final`` 版本优先，无则回退最新版（按
        ``cutoff_at`` 倒序）。``owner_user_id=None`` → 公共日报（NULL 归属）；
        ``int`` → 严格匹配该用户的私有日报。
        """
        final_stmt = (
            select(self.model)
            .where(self.model.report_date == report_date)
            .where(self.model.edition == "final")
            .where(self._owner_clause(owner_user_id))
            .where(self.model.status == "DONE")
            .order_by(self.model.cutoff_at.desc())
            .limit(1)
        )
        result = await self.db.execute(final_stmt)
        final_report = result.scalar_one_or_none()
        if final_report:
            return final_report

        stmt = (
            select(self.model)
            .where(self.model.report_date == report_date)
            .where(self._owner_clause(owner_user_id))
            .where(self.model.status == "DONE")
            .order_by(self.model.cutoff_at.desc(), self.model.updated_at.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_done_by_date_range(
        self,
        start_iso: str,
        end_iso: str,
    ) -> Sequence[DailyReport]:
        """查指定日期范围内 status='DONE' 的日报，供周报 pick-tracking 统计使用。

        排序按 report_date 升序，保证周报遍历日期顺序正确。
        """
        stmt = (
            select(self.model)
            .where(
                self.model.report_date >= start_iso,
                self.model.report_date <= end_iso,
                self.model.status == "DONE",
            )
            .order_by(self.model.report_date)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def create_generating_placeholder(
        self,
        *,
        report_date_iso: str,
        weekday: str,
        edition: str,
        window_start,
        window_end,
        cutoff_at,
        status: str = "GENERATING",
        overview: str = "正在生成日报...",
    ) -> DailyReport:
        """创建并 db.add 一个 GENERATING 占位日报记录，返回实例引用。

        供 trigger_generate_version 端点使用——api 层不直接 import ORM 模型类，
        也不直接 db.add。实例属性修改（如 status / updated_at）由调用方负责，
        最终 db.commit() 也由调用方控制事务边界。
        """
        report = self.model(
            report_date=report_date_iso,
            weekday=weekday,
            edition=edition,
            window_start=window_start,
            window_end=window_end,
            cutoff_at=cutoff_at,
            status=status,
            overview=overview,
        )
        self.db.add(report)
        return report
