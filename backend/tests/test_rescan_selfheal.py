"""调度器 rescan 自愈回归（#6 / 矩阵第 8 行生命周期补充）。

钉死 `_rescan_sources` 的 stale SYNCING 自愈契约（生产曾因 SYNCING 卡死
触发该修复，此前没有任何回归护栏）：

- SYNCING 且 `last_sync_at` 超过 3×lease 的源 → 重置 ACTIVE 并在
  `sync_error` 留下 "auto-reset from stale SYNCING" 痕迹；
- 未超时的 SYNCING 源（他人正常持有租约）与 ACTIVE 源不受影响。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.scheduler as scheduler_mod
from app.core.database import Base
from app.models.source import Source, SourceStatus, SourceType


@pytest.mark.asyncio
async def test_rescan_selfheals_stale_syncing_only(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # _rescan_sources 内部走全局 async_session；换成测试自有引擎，
    # 与同套件的 claim 回归（test_content_pipeline.py）保持同一模式。
    monkeypatch.setattr(scheduler_mod, "async_session", session_factory)

    now = datetime.now(UTC)
    try:
        async with session_factory() as db:
            db.add_all(
                [
                    Source(
                        id=1,
                        name="stale-syncing",
                        url="https://example.com/stale",
                        source_type=SourceType.RSS,
                        enabled=True,
                        status=SourceStatus.SYNCING,
                        last_sync_at=now - timedelta(seconds=3600),
                    ),
                    Source(
                        id=2,
                        name="fresh-syncing",
                        url="https://example.com/fresh",
                        source_type=SourceType.RSS,
                        enabled=True,
                        status=SourceStatus.SYNCING,
                        last_sync_at=now,
                    ),
                    Source(
                        id=3,
                        name="active",
                        url="https://example.com/active",
                        source_type=SourceType.RSS,
                        enabled=True,
                        status=SourceStatus.ACTIVE,
                        last_sync_at=now - timedelta(seconds=3600),
                    ),
                ]
            )
            await db.commit()

        await scheduler_mod._rescan_sources()

        async with session_factory() as db:
            stale = await db.get(Source, 1)
            fresh = await db.get(Source, 2)
            active = await db.get(Source, 3)

            assert stale.status == SourceStatus.ACTIVE
            assert stale.sync_error == "auto-reset from stale SYNCING"

            assert fresh.status == SourceStatus.SYNCING
            assert fresh.sync_error is None

            assert active.status == SourceStatus.ACTIVE
    finally:
        await engine.dispose()
