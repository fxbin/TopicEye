from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Date
from sqlalchemy.dialects import postgresql

from app.services import webnovel_report


@pytest.mark.asyncio
async def test_weekly_report_passes_native_dates_to_trending_history(monkeypatch):
    calls: list[tuple[str, date, date]] = []

    async def fake_fanqie_history(*_args):
        return {
            "snapshot_dates": [],
            "daily_counts": [],
            "rank_movements": [],
            "category_mix": [],
            "read_count_delta": 0,
        }

    async def fake_trending_history(_db, source, start_date, end_date):
        calls.append((source, start_date, end_date))
        return {"snapshot_dates": [], "daily_counts": [], "rank_movements": []}

    async def fake_current(*_args):
        return 0, []

    async def fake_current_with_categories(*_args):
        return 0, [], []

    monkeypatch.setattr(webnovel_report, "_fanqie_history", fake_fanqie_history)
    monkeypatch.setattr(webnovel_report, "_fanqie_current", fake_current)
    monkeypatch.setattr(webnovel_report, "_qimao_current", fake_current_with_categories)
    monkeypatch.setattr(webnovel_report, "_zhihu_current", fake_current_with_categories)
    monkeypatch.setattr(webnovel_report, "_trending_history", fake_trending_history)
    monkeypatch.setattr(webnovel_report, "_trending_current", fake_current)

    await webnovel_report.build_weekly_webnovel_report(object(), days=7)

    assert {source for source, _, _ in calls} == {"heiyan", "ishugui"}
    assert all(isinstance(start_date, date) for _, start_date, _ in calls)
    assert all(isinstance(end_date, date) for _, _, end_date in calls)


@pytest.mark.asyncio
async def test_trending_history_uses_postgresql_date_bindings():
    class EmptyResult:
        def scalars(self):
            return self

        def all(self):
            return []

    class CapturingSession:
        statement = None

        async def execute(self, statement):
            self.statement = statement
            return EmptyResult()

    session = CapturingSession()
    await webnovel_report._trending_history(session, "heiyan", date(2026, 7, 31), date(2026, 8, 6))

    assert session.statement is not None
    compiled = session.statement.compile(dialect=postgresql.dialect())
    date_bindings = [binding for key, binding in compiled.binds.items() if key.startswith("snapshot_date")]
    assert len(date_bindings) == 2
    assert all(isinstance(binding.type, Date) for binding in date_bindings)
