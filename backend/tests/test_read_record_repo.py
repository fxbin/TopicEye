from datetime import datetime, timedelta, UTC

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
import app.models.read_record  # noqa: F401  — ensure table on metadata
from app.models.read_record import ReadDepth, ReadTargetType
from app.repositories.read_record_repo import ReadRecordRepository


@pytest.mark.asyncio
async def test_add_new_creates_record_with_defaults():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)
        record = repo.add_new(
            user_id=1,
            target_type=ReadTargetType.DAILY_REPORT,
            target_key="2026-07-22",
            duration_ms=5000,
            topic_keywords=["AI", "新能源"],
        )
        await db.flush()
        await db.refresh(record)

        assert record.id is not None
        assert record.read_count == 1
        assert record.accumulated_ms == 5000
        assert record.depth == ReadDepth.READ
        assert record.max_progress == 0
        assert record.topic_keywords == ["AI", "新能源"]
        assert record.first_read_at is not None
        assert record.last_read_at is not None

    await engine.dispose()


@pytest.mark.asyncio
async def test_find_existing_returns_none_then_record():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)

        missing = await repo.find_existing(1, ReadTargetType.DAILY_REPORT, "2026-07-22")
        assert missing is None

        repo.add_new(
            user_id=1,
            target_type=ReadTargetType.DAILY_REPORT,
            target_key="2026-07-22",
        )
        await db.flush()

        found = await repo.find_existing(1, ReadTargetType.DAILY_REPORT, "2026-07-22")
        assert found is not None
        assert found.target_key == "2026-07-22"

    await engine.dispose()


@pytest.mark.asyncio
async def test_merge_session_accumulates_duration_and_count():
    """核心 upsert 语义：多次阅读累加，不插新行。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)
        record = repo.add_new(
            user_id=1,
            target_type=ReadTargetType.WEEKLY_DIGEST,
            target_key="2026-W29",
            duration_ms=3000,
            topic_keywords=["初始关键词"],
        )
        await db.flush()
        await db.refresh(record)
        original_last_read = record.last_read_at

        # 模拟第二次阅读会话上报
        await repo.merge_session(record, duration_ms=7000, topic_keywords=["新关键词"], category="科技")

        assert record.read_count == 2
        assert record.accumulated_ms == 10000
        # 快照首读固化：已有 topic_keywords 时不覆盖
        assert record.topic_keywords == ["初始关键词"]
        # category 原为空，回填
        assert record.category == "科技"
        assert record.last_read_at >= original_last_read

    await engine.dispose()


@pytest.mark.asyncio
async def test_merge_session_backfills_snapshot_when_empty():
    """首读未带快照时，后续会话可回填。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)
        record = repo.add_new(
            user_id=1,
            target_type=ReadTargetType.MONTHLY_DIGEST,
            target_key="2026-07",
        )
        await db.flush()

        await repo.merge_session(record, duration_ms=2000, topic_keywords=["回填关键词"])

        assert record.topic_keywords == ["回填关键词"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_delete_older_than_removes_only_expired():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)

        old = repo.add_new(user_id=1, target_type=ReadTargetType.DAILY_REPORT, target_key="2025-01-01")
        old.last_read_at = datetime.now(UTC) - timedelta(days=200)
        recent = repo.add_new(user_id=1, target_type=ReadTargetType.DAILY_REPORT, target_key="2026-07-22")
        await db.flush()

        cutoff = datetime.now(UTC) - timedelta(days=180)
        removed = await repo.delete_older_than(cutoff)

        assert removed == 1
        remaining = await repo.list_by_user(1)
        assert len(remaining) == 1
        assert remaining[0].target_key == "2026-07-22"

    await engine.dispose()


@pytest.mark.asyncio
async def test_list_by_user_filters_by_target_type():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)
        repo.add_new(user_id=1, target_type=ReadTargetType.DAILY_REPORT, target_key="2026-07-21")
        repo.add_new(user_id=1, target_type=ReadTargetType.DAILY_REPORT, target_key="2026-07-22")
        repo.add_new(user_id=1, target_type=ReadTargetType.WEEKLY_DIGEST, target_key="2026-W29")
        await db.flush()

        all_items = await repo.list_by_user(1)
        assert len(all_items) == 3

        daily_only = await repo.list_by_user(1, target_type=ReadTargetType.DAILY_REPORT)
        assert len(daily_only) == 2
        assert all(r.target_type == ReadTargetType.DAILY_REPORT for r in daily_only)

    await engine.dispose()


@pytest.mark.asyncio
async def test_records_are_user_scoped():
    """不同用户的记录互不可见。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        repo = ReadRecordRepository(db)
        repo.add_new(user_id=1, target_type=ReadTargetType.DAILY_REPORT, target_key="2026-07-22")
        repo.add_new(user_id=2, target_type=ReadTargetType.DAILY_REPORT, target_key="2026-07-22")
        await db.flush()

        user1 = await repo.list_by_user(1)
        user2 = await repo.list_by_user(2)
        assert len(user1) == 1
        assert len(user2) == 1
        assert user1[0].user_id == 1
        assert user2[0].user_id == 2

    await engine.dispose()
