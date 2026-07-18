"""Unified time helpers for TopicEye backend.

All code should import from here instead of using ``datetime.utcnow()``,
``datetime.now(UTC)``, or defining local ``_utc_now()`` functions.

- ``utc_now()``        → aware UTC datetime (Python-layer comparisons)
- ``naive_utc_now()``  → naive UTC datetime (SQL bind params for aiosqlite)

For converting existing datetimes, use ``ensure_aware_utc`` /
``ensure_naive_utc`` from ``app.core.db_backend``.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return the current UTC time as an **aware** datetime.

    Use for Python-layer comparisons (e.g. ``now - some_timestamp``).
    """
    return datetime.now(UTC)


def naive_utc_now() -> datetime:
    """Return the current UTC time as a **naive** datetime.

    Use for SQLAlchemy where-clause bind parameters:
    - aiosqlite rejects aware datetime as a bind param
    - asyncpg interprets naive as UTC when the session timezone is UTC

    Equivalent to ``datetime.now(UTC).replace(tzinfo=None)``.
    """
    return datetime.now(UTC).replace(tzinfo=None)
