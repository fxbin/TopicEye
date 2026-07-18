from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Optional, TypeVar

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import database_profile

T = TypeVar("T")


def is_sqlite_locked(exc: BaseException) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database table is locked" in message


async def retry_sqlite_locked[T](
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 0.15,
    on_retry: Callable[[], Awaitable[None]] | None = None,
) -> T:
    last_exc: OperationalError | None = None
    for index in range(attempts):
        try:
            return await operation()
        except OperationalError as exc:
            if not is_sqlite_locked(exc) or index == attempts - 1:
                raise
            last_exc = exc
            if on_retry is not None:
                await on_retry()
            await asyncio.sleep(base_delay * (2**index))

    raise last_exc  # pragma: no cover


async def begin_immediate_for_sqlite(db: AsyncSession) -> None:
    """Acquire SQLite's write lock up front to avoid deferred lock upgrades."""
    if not database_profile.is_sqlite:
        return
    await db.execute(text("BEGIN IMMEDIATE"))


async def retry_write_transaction[T](
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
) -> T:
    """Run *operation* inside a SQLite-safe write transaction with retry.

    Combines the two pieces every write endpoint in the API layer repeats:
    1. ``BEGIN IMMEDIATE`` on SQLite (no-op on Postgres) to avoid deferred
       lock upgrades that surface as ``database is locked`` mid-flush.
    2. ``retry_sqlite_locked`` with ``on_retry=db.rollback`` so transient
       lock contention is retried instead of surfacing as 500.

    Callers still own ``db.commit()`` — this helper only guarantees the
    flush/operation succeeds or raises ``OperationalError`` for the caller
    to translate into an HTTP response.
    """
    if database_profile.is_sqlite and not db.in_transaction():
        await begin_immediate_for_sqlite(db)

    async def _wrapped() -> T:
        return await operation()

    return await retry_sqlite_locked(_wrapped, on_retry=db.rollback)
