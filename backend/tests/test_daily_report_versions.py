import json
from datetime import date, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.selectable import Select

from app.core.database import Base
from app.models.daily_report import DailyReport
from app.services import daily_report
from app.services.daily_report import (
    GENERATING_STALE_AFTER,
    _day_window,
    _local_window_to_utc_naive,
    _normalize_edition,
)


def test_snapshot_window_uses_start_of_target_day_to_cutoff():
    start, end = _day_window(
        date(2026, 5, 27),
        datetime(2026, 5, 27, 12, 0, 30),
        "noon",
    )

    assert start == datetime(2026, 5, 27, 0, 0, 0)
    assert end == datetime(2026, 5, 27, 12, 0, 30)


def test_final_window_covers_full_target_day():
    start, end = _day_window(date(2026, 5, 27), None, "final")

    assert start == datetime(2026, 5, 27, 0, 0, 0)
    assert end == datetime(2026, 5, 27, 23, 59, 59)


def test_past_date_defaults_to_final_edition():
    assert _normalize_edition(None, date(2020, 1, 1), None) == "final"


def test_report_window_queries_utc_storage_range():
    start, end = _local_window_to_utc_naive(
        datetime(2026, 5, 27, 0, 0, 0),
        datetime(2026, 5, 27, 12, 0, 0),
    )

    assert start == datetime(2026, 5, 26, 16, 0, 0)
    assert end == datetime(2026, 5, 27, 4, 0, 0)


@pytest.mark.asyncio
async def test_generate_daily_report_returns_active_generating_without_llm(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    monkeypatch.setattr(daily_report, "_local_now", lambda: now)

    async def fail_fetch_inputs(*_args, **_kwargs):
        raise AssertionError("active GENERATING report should not generate again")

    monkeypatch.setattr(daily_report, "_fetch_report_inputs", fail_fetch_inputs)
    start, end = _day_window(date(2026, 5, 27), now, "noon")
    async with session_factory() as db:
        existing = DailyReport(
            report_date="2026-05-27",
            weekday="周三",
            edition="noon",
            generated_at=now - timedelta(minutes=1),
            window_start=start,
            window_end=end,
            cutoff_at=end,
            status="GENERATING",
        )
        db.add(existing)
        await db.commit()

        report = await daily_report.generate_daily_report(
            db,
            target_date=date(2026, 5, 27),
            edition="noon",
            cutoff_at=now,
            force=False,
        )

    assert report.id == existing.id
    assert report.status == "GENERATING"
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_daily_report_reclaims_stale_generating(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    monkeypatch.setattr(daily_report, "_local_now", lambda: now)

    async def fake_fetch_inputs(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(daily_report, "_fetch_report_inputs", fake_fetch_inputs)
    start, end = _day_window(date(2026, 5, 27), now, "noon")
    async with session_factory() as db:
        existing = DailyReport(
            report_date="2026-05-27",
            weekday="周三",
            edition="noon",
            generated_at=now - GENERATING_STALE_AFTER - timedelta(seconds=1),
            window_start=start,
            window_end=end,
            cutoff_at=end,
            status="GENERATING",
        )
        db.add(existing)
        await db.commit()

        report = await daily_report.generate_daily_report(
            db,
            target_date=date(2026, 5, 27),
            edition="noon",
            cutoff_at=now,
            force=False,
        )

    assert report.id == existing.id
    assert report.status == "ERROR"
    assert "暂无分析数据" in report.overview
    await engine.dispose()


@pytest.mark.asyncio
async def test_generate_daily_report_locks_existing_row_for_postgresql(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    calls = {"for_update": 0}
    monkeypatch.setattr(daily_report, "_local_now", lambda: now)

    class FakeProfile:
        is_sqlite = False
        is_postgresql = True

    monkeypatch.setattr(daily_report, "database_profile", FakeProfile())
    original_with_for_update = Select.with_for_update

    def with_for_update_spy(self, *args, **kwargs):
        calls["for_update"] += 1
        return original_with_for_update(self, *args, **kwargs)

    async def fake_fetch_inputs(*_args, **_kwargs):
        return [], []

    monkeypatch.setattr(Select, "with_for_update", with_for_update_spy)
    monkeypatch.setattr(daily_report, "_fetch_report_inputs", fake_fetch_inputs)

    start, end = _day_window(date(2026, 5, 27), now, "noon")
    async with session_factory() as db:
        db.add(
            DailyReport(
                report_date="2026-05-27",
                weekday="周三",
                edition="noon",
                generated_at=now - GENERATING_STALE_AFTER - timedelta(seconds=1),
                window_start=start,
                window_end=end,
                cutoff_at=end,
                status="GENERATING",
            )
        )
        await db.commit()

        report = await daily_report.generate_daily_report(
            db,
            target_date=date(2026, 5, 27),
            edition="noon",
            cutoff_at=now,
            force=False,
        )

    assert calls["for_update"] == 1
    assert report.status == "ERROR"
    await engine.dispose()


@pytest.mark.asyncio
async def test_invalid_llm_daily_report_uses_editorial_fallback(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    item = {
        "id": 1,
        "title": "AI 视频工具开始争夺创作者工作流",
        "url": "https://example.com/a",
        "category": "产品更新",
        "source_name": "技术观察",
        "creator_score": 86.0,
        "viral_score": 75.0,
        "quality_score": 80.0,
        "risk_score": 20.0,
        "curation_score": 86.0,
        "adjusted_score": 86.0,
        "summary": "多家平台更新视频生成能力，重点面向短视频和营销素材。",
        "recommendation": "适合拆解成创作者工具选型和实测对比。",
    }

    async def fake_inputs(*_args, **_kwargs):
        return [item], [item]

    async def invalid_llm(*_args, **_kwargs):
        return {"raw_response": "not-json"}

    monkeypatch.setattr(daily_report, "_local_now", lambda: now)
    monkeypatch.setattr(daily_report, "_fetch_report_inputs", fake_inputs)
    monkeypatch.setattr(daily_report, "call_llm_json", invalid_llm)

    async with session_factory() as db:
        report = await daily_report.generate_daily_report(
            db,
            target_date=date(2026, 5, 27),
            edition="noon",
            cutoff_at=now,
        )

    picks = json.loads(report.top_picks)
    assert report.status == "DONE"
    assert "今天先写" in report.overview
    assert picks[0]["source_url"] == item["url"]
    assert picks[0]["source_title"] == item["title"]
    assert picks[0]["tier"] == "feature"
    assert picks[0]["angles"]
    assert "lifecycle" not in picks[0]
    await engine.dispose()


@pytest.mark.asyncio
async def test_daily_report_without_curated_items_is_done_without_background_recommendations(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime(2026, 5, 27, 12, 0, 0)
    background_item = {
        "id": 7,
        "title": "只可作为背景的素材",
        "url": "https://example.com/background",
        "category": "行业动态",
        "source_name": "技术观察",
        "curation_score": 48.0,
        "summary": "这条素材只能帮助判断当天背景。",
    }

    async def fake_inputs(*_args, **_kwargs):
        return [], [background_item]

    async def should_not_call_llm(*_args, **_kwargs):
        raise AssertionError("no curated items must not call the LLM")

    monkeypatch.setattr(daily_report, "_local_now", lambda: now)
    monkeypatch.setattr(daily_report, "_fetch_report_inputs", fake_inputs)
    monkeypatch.setattr(daily_report, "call_llm_json", should_not_call_llm)

    async with session_factory() as db:
        report = await daily_report.generate_daily_report(
            db,
            target_date=date(2026, 5, 27),
            edition="noon",
            cutoff_at=now,
        )

    assert report.status == "DONE"
    assert "暂未形成可推荐精选" in report.overview
    assert json.loads(report.top_picks) == []
    assert json.loads(report.source_item_ids) == []
    await engine.dispose()
