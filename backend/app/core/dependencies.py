"""
FastAPI dependency injection helpers.

Centralises all commonly-used dependencies so routes don't import
infrastructure modules directly.

``get_db`` is defined in ``app.core.database`` (next to ``async_session``)
and re-exported here to avoid a circular import.
"""

from __future__ import annotations

from app.core.database import get_db  # noqa: F401 — re-export for API routes

__all__ = ["get_db"]
