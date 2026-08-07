"""Shared write helpers for API endpoints — error handling + rollback.

Provides consistent error handling for write endpoints:
- Run the operation
- On OperationalError: rollback and re-raise (FastAPI's default 500 handler runs)
- On success: return result

The previous SQLite-specific retry and busy_timeout logic has been removed
along with SQLite backend support. PostgreSQL handles concurrent writes
without application-level retry.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

T = TypeVar("T")


async def write_with_503(
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
) -> T:
    """Run *operation* with rollback on error.

    ``attempts`` and ``base_delay`` are accepted for backward compatibility
    but no longer used — PostgreSQL does not need application-level retry.
    """
    try:
        return await operation()
    except OperationalError:
        await db.rollback()
        raise


async def write_with_503_low_latency(
    db: AsyncSession,
    operation: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.1,
) -> T:
    """Like :func:`write_with_503` — kept for call-site compatibility."""
    try:
        return await operation()
    except OperationalError:
        await db.rollback()
        raise
