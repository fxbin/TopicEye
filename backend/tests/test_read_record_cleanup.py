"""阅读记录保留期清理测试。

覆盖 read_record_service.cleanup_old_records 按 last_read_at 清理过期记录。
"""

from __future__ import annotations

from datetime import UTC, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models.read_record  # noqa: F401
import app.models.user  # noqa: F401
from app.core.database import Base
from app.models.read_record import ReadRecord, ReadTargetType
from app.services.read_record_service import cleanup_old_records


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_records():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from datetime import datetime

    async with session_factory() as db:
        now = datetime.now(UTC)
        # 200 天前（过期）
        old = ReadRecord(
            user_id=1,
            target_type=ReadTargetType.DAILY_REPORT,
            target_key="2025-01-01",
            first_read_at=now - timedelta(days=200),
            last_read_at=now - timedelta(days=200),
        )
        # 10 天前（保留）
        recent = ReadRecord(
            user_id=1,
            target_type=ReadTargetType.DAILY_REPORT,
            target_key="2026-07-12",
            first_read_at=now - timedelta(days=10),
            last_read_at=now - timedelta(days=10),
        )
        db.add_all([old, recent])
        await db.commit()

        removed = await cleanup_old_records(db, days=180)
        await db.commit()

        assert removed == 1
        from sqlalchemy import func, select

        count = (await db.execute(select(func.count()).select_from(ReadRecord))).scalar()
        assert count == 1

    await engine.dispose()


@pytest.mark.asyncio
async def test_cleanup_with_custom_retention_window():
    """保留期可配置：30 天窗口会清理更多。"""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    from datetime import datetime

    async with session_factory() as db:
        now = datetime.now(UTC)
        records = [
            ReadRecord(
                user_id=1,
                target_type=ReadTargetType.DAILY_REPORT,
                target_key=f"2026-07-{i:02d}",
                first_read_at=now - timedelta(days=age),
                last_read_at=now - timedelta(days=age),
            )
            for i, age in enumerate([5, 40, 100, 200], start=1)
        ]
        db.add_all(records)
        await db.commit()

        removed = await cleanup_old_records(db, days=30)
        await db.commit()
        assert removed == 3  # 40/100/200 天的都被清

    await engine.dispose()
