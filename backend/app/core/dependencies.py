"""
FastAPI dependency injection helpers.

Centralises all commonly-used dependencies so routes don't import
infrastructure modules directly.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Yield a database session with auto-commit/rollback/close."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
