"""验证 datetime 列的 aware 声明 + ensure_aware_utc helper 行为.

覆盖:
1. 所有 model 的 DateTime 列声明 timezone=True
2. ensure_aware_utc 工具函数对 naive/aware/None 的处理
3. SQLite 端写入 aware datetime 不报错 (即使底层丢 tzinfo)
"""

from __future__ import annotations

from datetime import UTC, datetime, timezone

import pytest
from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import create_async_engine

import app.models  # noqa: F401  # register all models in Base.metadata
from app.core.database import Base
from app.core.db_backend import ensure_aware_utc


def test_all_datetime_columns_declared_tz_aware():
    """所有 model 的 DateTime 列都应该是 timezone=True.

    新增 model 时如果忘了加 timezone=True 会立即失败, 防止回退到 naive.
    """
    non_tz: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        for col in table.columns:
            if isinstance(col.type, DateTime) and not col.type.timezone:
                non_tz.append(f"{table_name}.{col.name}")
    assert not non_tz, f"这些 DateTime 列没声明 timezone=True: {non_tz}"


def test_ensure_aware_utc_none():
    assert ensure_aware_utc(None) is None


def test_ensure_aware_utc_naive_assumed_utc():
    """SQLite 读出的 naive datetime 应被当作 UTC."""
    naive = datetime(2024, 1, 1, 12, 0, 0)
    aware = ensure_aware_utc(naive)
    assert aware is not None
    assert aware.tzinfo is not None
    assert aware.utcoffset() == UTC.utcoffset(datetime.now(UTC))
    # 值不变
    assert aware.replace(tzinfo=None) == naive


def test_ensure_aware_utc_already_aware():
    """已经是 aware 的转 UTC (其他时区会转换)."""
    from datetime import timedelta

    # +08:00 时区, 12:00 → UTC 04:00
    cst = timezone(timedelta(hours=8))
    aware_cst = datetime(2024, 1, 1, 12, 0, 0, tzinfo=cst)
    aware_utc = ensure_aware_utc(aware_cst)
    assert aware_utc is not None
    assert aware_utc.utcoffset() == timedelta(0)
    assert aware_utc.hour == 4


@pytest.mark.asyncio
async def test_sqlite_aware_datetime_write_does_not_raise():
    """SQLite 端写入 aware datetime 不应抛错 (即使 SQLite 底层丢 tzinfo).

    回归测试: PG 迁移期发现 SQLite aware 行为不一致, 这个测试保证
    至少写入路径不挂 (读取路径用 ensure_aware_utc 兜底).
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 用 Source 这个常见 model, 写入 last_sync_at (aware)
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm import sessionmaker

    from app.models.source import Source

    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        src = Source(
            name="test-tz",
            url="https://example.com/feed.xml",
            source_type="rss",
            enabled=True,
            status="active",
            last_sync_at=datetime.now(UTC),
        )
        session.add(src)
        await session.commit()

    # 读取回来, SQLite 返回 naive, ensure_aware_utc 兜底
    async with async_session() as session:
        result = await session.execute(select(Source).where(Source.name == "test-tz"))
        row = result.scalar_one_or_none()
        assert row is not None
        # SQLite 读出来可能是 naive, 但 helper 能转
        normalized = ensure_aware_utc(row.last_sync_at)
        assert normalized is not None
        assert normalized.tzinfo is not None

    await engine.dispose()
