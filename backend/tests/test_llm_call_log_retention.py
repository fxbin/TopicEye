"""LLM 调用记录保留期（#191）。

这张表原来只增不减、没有保留期。本次定 30 天并加每日清理任务，
要钉住三件事：

- 清理只删超期行，窗口内的行必须留下；
- 边界语义明确（``created_at < cutoff`` 才删，正好等于起点的那行保留）；
- **预算熔断不能被清理打断**：它的三窗最长是 24 小时，清理后最近一天内的
  DONE 记录仍要能被 ``count_recent_llm_calls`` 数到。

走内存 SQLite（快；这张表没有 PG 专属约束依赖）。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.core.database import Base
from app.models.llm_model import LlmCallLog
from app.repositories.llm_call_log_repo import LlmCallLogRepository
from app.services.llm_usage import LLM_CALL_LOG_RETENTION_DAYS, cleanup_old_call_logs


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield factory
    await engine.dispose()


def _row(request_id: str, *, age_days: float, status: str = "DONE") -> LlmCallLog:
    return LlmCallLog(
        request_id=request_id,
        scene="analysis",
        status=status,
        duration_ms=10,
        created_at=datetime.now(UTC) - timedelta(days=age_days),
    )


async def _ids(db) -> set[str]:
    result = await db.execute(select(LlmCallLog.request_id))
    return set(result.scalars().all())


def test_retention_is_30_days():
    """把策略钉死：改动保留期必须同时改这个断言。"""
    assert LLM_CALL_LOG_RETENTION_DAYS == 30


@pytest.mark.asyncio
async def test_cleanup_removes_only_expired_rows(session_factory):
    async with session_factory() as db:
        db.add(_row("expired", age_days=LLM_CALL_LOG_RETENTION_DAYS + 1))
        db.add(_row("inside", age_days=LLM_CALL_LOG_RETENTION_DAYS - 1))
        await db.commit()

        removed = await cleanup_old_call_logs(db)
        await db.commit()

        assert removed == 1
        assert await _ids(db) == {"inside"}


@pytest.mark.asyncio
async def test_cleanup_keeps_row_exactly_at_cutoff(session_factory):
    """边界：正好等于保留期起点的那行保留（删除条件是严格小于）。"""
    cutoff = datetime.now(UTC) - timedelta(days=LLM_CALL_LOG_RETENTION_DAYS)
    async with session_factory() as db:
        db.add(LlmCallLog(request_id="at-cutoff", scene="analysis", status="DONE", created_at=cutoff))
        db.add(
            LlmCallLog(
                request_id="before-cutoff",
                scene="analysis",
                status="DONE",
                created_at=cutoff - timedelta(seconds=1),
            )
        )
        await db.commit()

        removed = await LlmCallLogRepository(db).delete_older_than(cutoff)
        await db.commit()

        assert removed == 1
        assert await _ids(db) == {"at-cutoff"}


@pytest.mark.asyncio
async def test_cleanup_keeps_rows_inside_budget_guard_window(session_factory):
    """预算熔断读 DONE 调用数，最长窗口 24 小时——清理不能把它清空。"""
    async with session_factory() as db:
        db.add(_row("recent", age_days=0.5))
        db.add(_row("yesterday", age_days=1.0))
        db.add(_row("expired", age_days=LLM_CALL_LOG_RETENTION_DAYS + 1))
        await db.commit()

        removed = await cleanup_old_call_logs(db)
        await db.commit()

        assert removed == 1
        remaining = await _ids(db)
        assert remaining == {"recent", "yesterday"}


@pytest.mark.asyncio
async def test_cleanup_accepts_custom_days(session_factory):
    """保留天数可传参，便于测试与临时调整。"""
    async with session_factory() as db:
        db.add(_row("two-days", age_days=2))
        db.add(_row("ten-days", age_days=10))
        await db.commit()

        removed = await cleanup_old_call_logs(db, days=7)
        await db.commit()

        assert removed == 1
        assert await _ids(db) == {"two-days"}


@pytest.mark.asyncio
async def test_cleanup_is_idempotent(session_factory):
    """重复清理不报错，第二次删 0 条。"""
    async with session_factory() as db:
        db.add(_row("expired", age_days=LLM_CALL_LOG_RETENTION_DAYS + 1))
        await db.commit()

        assert await cleanup_old_call_logs(db) == 1
        await db.commit()
        assert await cleanup_old_call_logs(db) == 0
        await db.commit()
