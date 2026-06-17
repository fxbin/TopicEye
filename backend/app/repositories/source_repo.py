"""
Repository for Source model operations.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.source import Source, SourceStatus
from app.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    """Source table CRUD + enabled-sources query."""

    model = Source

    async def get_enabled_sources(self) -> Sequence[Source]:
        """Return syncable sources in the user-managed order."""
        stmt = (
            select(Source)
            .where(
                Source.enabled.is_(True),
                Source.status != SourceStatus.DISABLED,
            )
            .order_by(Source.sort_order.asc(), Source.id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def claim_sync(
        self,
        source_id: int,
        *,
        lease_seconds: int,
        min_interval_seconds: int = 0,
    ) -> Source | None:
        """Claim one source for sync, returning None when another run owns it."""
        return await claim_source_sync(
            self.db,
            source_id,
            lease_seconds=lease_seconds,
            min_interval_seconds=min_interval_seconds,
        )


async def claim_source_sync(
    db: AsyncSession,
    source_id: int,
    *,
    lease_seconds: int,
    min_interval_seconds: int = 0,
) -> Source | None:
    """Acquire a cross-process source-sync lease via ``last_sync_at``."""
    now = datetime.now(timezone.utc)
    lease_cutoff = now - timedelta(seconds=max(int(lease_seconds), 1))
    interval_cutoff = now - timedelta(seconds=max(int(min_interval_seconds), 0))

    async def _claim() -> Source | None:
        await begin_immediate_for_sqlite(db)
        result = await db.execute(select(Source).where(Source.id == source_id).with_for_update())
        source = result.scalar_one_or_none()
        if source is None:
            return None
        if not source.enabled or source.status == SourceStatus.DISABLED:
            return None
        # DB (SQLite) 读出 last_sync_at 可能是 naive, 统一 aware UTC 再比较
        from app.core.db_backend import ensure_aware_utc

        last_sync_aware = ensure_aware_utc(source.last_sync_at)
        if source.status == SourceStatus.SYNCING and last_sync_aware is not None and last_sync_aware > lease_cutoff:
            return None
        if min_interval_seconds > 0 and last_sync_aware is not None and last_sync_aware > interval_cutoff:
            return None

        source.last_sync_at = now
        source.status = SourceStatus.SYNCING
        source.sync_error = None
        source.updated_at = now
        await db.flush()
        return source

    return await retry_sqlite_locked(_claim, on_retry=db.rollback)
