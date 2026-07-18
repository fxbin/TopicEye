"""Shared write helpers for API endpoints — SQLite retry + 503 translation.

Every write endpoint that needs low-latency 503 on SQLite contention repeats
the same try/except shape:

    try:
        async with _LowLatencyBusyTimeout(db):
            result = await retry_sqlite_locked(_write, ...)
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(503, "数据库繁忙，请稍后重试") from exc
        raise

This module collapses that into one call. Two variants:

- :func:`write_with_503` — plain retry (no busy_timeout tweaking).
- :func:`write_with_503_low_latency` — also lowers ``busy_timeout`` for the
  duration of the write so batch writers get fast 503 instead of waiting.
  Matches the old ``_LowLatencyBusyTimeout`` behaviour used by the favorite /
  ignore endpoints in ``contents.py``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import database_profile
from app.core.sqlite_retry import is_sqlite_locked, retry_sqlite_locked

T = TypeVar("T")

_SQLITE_BUSY_DETAIL = "数据库繁忙，请稍后重试"


async def write_with_503(
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
) -> T:
    """Run *operation* with SQLite-lock retry; translate lock errors to 503.

    On ``OperationalError`` that is NOT a lock error, the original exception
    is re-raised (after rollback) so FastAPI's default 500 handler runs.
    """
    try:
        return await retry_sqlite_locked(
            operation, attempts=attempts, base_delay=base_delay, on_retry=db.rollback
        )
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail=_SQLITE_BUSY_DETAIL) from exc
        raise


class _LowLatencyBusyTimeout:
    """Temporarily lower SQLite ``busy_timeout`` so batch writes fail fast.

    Non-SQLite backends: no-op.
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        self._active = False

    async def __aenter__(self) -> _LowLatencyBusyTimeout:
        if database_profile.is_sqlite:
            try:
                await self._db.execute(text(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_BATCH_MS}"))
                self._active = True
            except Exception:
                await self._db.rollback()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._active:
            try:
                await self._db.execute(text(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_MS}"))
            except Exception:
                await self._db.rollback()
            self._active = False


async def write_with_503_low_latency(
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
) -> T:
    """Like :func:`write_with_503` but also lower ``busy_timeout`` for the write.

    Use this for user-facing favorite/ignore endpoints where a fast 503 is
    preferable to making the client wait behind a batch indexer.
    """
    try:
        async with _LowLatencyBusyTimeout(db):
            return await retry_sqlite_locked(
                operation, attempts=attempts, base_delay=base_delay, on_retry=db.rollback
            )
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail=_SQLITE_BUSY_DETAIL) from exc
        raise
