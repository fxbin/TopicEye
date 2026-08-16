"""Persistence boundary for incremental content-event normalization."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem, ContentStatus
from app.models.content_event import (
    ContentEventGroup,
    ContentEventMember,
    EventStatus,
)
from app.models.content_event_run import (
    ContentEventNormalizationLease,
    ContentEventNormalizationRun,
)


@dataclass(frozen=True)
class HistoricalCanonical:
    event_group: ContentEventGroup
    content: ContentItem


class ContentEventNormalizationRepository:
    """All ORM access needed by the normalization worker."""

    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _owner_clause(owner_user_id: int | None):
        if owner_user_id is None:
            return ContentItem.owner_user_id.is_(None)
        return ContentItem.owner_user_id == owner_user_id

    @staticmethod
    def _group_owner_clause(owner_user_id: int | None):
        if owner_user_id is None:
            return ContentEventGroup.owner_user_id.is_(None)
        return ContentEventGroup.owner_user_id == owner_user_id

    async def begin_claim_transaction(self) -> None:
        """No-op — PostgreSQL handles row-level locking via SELECT FOR UPDATE."""
        pass

    async def get_run(
        self,
        *,
        scope_key: str,
        idempotency_key: str,
        for_update: bool = False,
    ) -> ContentEventNormalizationRun | None:
        stmt = select(ContentEventNormalizationRun).where(
            ContentEventNormalizationRun.scope_key == scope_key,
            ContentEventNormalizationRun.idempotency_key == idempotency_key,
        )
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def claim_lease(
        self,
        *,
        scope_key: str,
        lease_token: str,
        now: datetime,
        expires_at: datetime,
    ) -> int | None:
        """Atomically acquire/renew one scope and return its fencing token."""

        stmt = (
            update(ContentEventNormalizationLease)
            .where(
                ContentEventNormalizationLease.scope_key == scope_key,
                or_(
                    ContentEventNormalizationLease.lease_token.is_(None),
                    ContentEventNormalizationLease.lease_expires_at.is_(None),
                    ContentEventNormalizationLease.lease_expires_at <= now,
                    ContentEventNormalizationLease.lease_token == lease_token,
                ),
            )
            .values(
                fencing_token=ContentEventNormalizationLease.fencing_token + 1,
                lease_token=lease_token,
                lease_expires_at=expires_at,
                updated_at=now,
            )
            .returning(ContentEventNormalizationLease.fencing_token)
        )
        result = await self.db.execute(stmt)
        fencing_token = result.scalar_one_or_none()
        if fencing_token is not None:
            return int(fencing_token)

        existing = await self.db.get(ContentEventNormalizationLease, scope_key)
        if existing is not None:
            return None

        lease = ContentEventNormalizationLease(
            scope_key=scope_key,
            fencing_token=1,
            lease_token=lease_token,
            lease_expires_at=expires_at,
            updated_at=now,
        )
        self.db.add(lease)
        await self.db.flush()
        return 1

    async def create_run(self, **values) -> ContentEventNormalizationRun:
        run = ContentEventNormalizationRun(**values)
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_run_by_id(
        self,
        run_id: int,
        *,
        for_update: bool = False,
    ) -> ContentEventNormalizationRun | None:
        stmt = select(ContentEventNormalizationRun).where(ContentEventNormalizationRun.id == run_id)
        if for_update:
            stmt = stmt.with_for_update()
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def reclaim_run(
        self,
        run: ContentEventNormalizationRun,
        *,
        mode: str,
        lease_token: str,
        fencing_token: int,
        started_at: datetime,
        window_hours: int,
    ) -> None:
        run.mode = mode
        run.status = "running"
        run.lease_token = lease_token
        run.fencing_token = fencing_token
        run.started_at = started_at
        run.window_hours = window_hours
        run.finished_at = None
        run.error_message = None
        await self.db.flush()

    async def lock_current_lease(
        self,
        *,
        scope_key: str,
        lease_token: str,
        fencing_token: int,
        now: datetime,
    ) -> bool:
        stmt = (
            select(ContentEventNormalizationLease)
            .where(
                ContentEventNormalizationLease.scope_key == scope_key,
                ContentEventNormalizationLease.lease_token == lease_token,
                ContentEventNormalizationLease.fencing_token == fencing_token,
                ContentEventNormalizationLease.lease_expires_at.is_not(None),
                ContentEventNormalizationLease.lease_expires_at > now,
            )
            .with_for_update()
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def renew_lease(
        self,
        *,
        scope_key: str,
        lease_token: str,
        fencing_token: int,
        expires_at: datetime,
        now: datetime,
    ) -> bool:
        stmt = (
            update(ContentEventNormalizationLease)
            .where(
                ContentEventNormalizationLease.scope_key == scope_key,
                ContentEventNormalizationLease.lease_token == lease_token,
                ContentEventNormalizationLease.fencing_token == fencing_token,
            )
            .values(lease_expires_at=expires_at, updated_at=now)
        )
        result = await self.db.execute(stmt)
        return bool(result.rowcount)

    async def release_lease(
        self,
        *,
        scope_key: str,
        lease_token: str,
        fencing_token: int,
        now: datetime,
    ) -> bool:
        stmt = (
            update(ContentEventNormalizationLease)
            .where(
                ContentEventNormalizationLease.scope_key == scope_key,
                ContentEventNormalizationLease.lease_token == lease_token,
                ContentEventNormalizationLease.fencing_token == fencing_token,
            )
            .values(
                lease_token=None,
                lease_expires_at=None,
                updated_at=now,
            )
        )
        result = await self.db.execute(stmt)
        return bool(result.rowcount)

    async def list_recent_unassigned(
        self,
        *,
        owner_user_id: int | None,
        since: datetime,
        limit: int,
    ) -> list[ContentItem]:
        canonical_exists = exists(
            select(ContentEventGroup.id).where(ContentEventGroup.canonical_content_id == ContentItem.id)
        )
        member_exists = exists(select(ContentEventMember.id).where(ContentEventMember.content_id == ContentItem.id))
        stmt = (
            select(ContentItem)
            .where(
                self._owner_clause(owner_user_id),
                ContentItem.created_at >= since,
                ContentItem.status == ContentStatus.ANALYZED,
                ~canonical_exists,
                ~member_exists,
            )
            .order_by(
                ContentItem.published_at.asc().nulls_last(),
                ContentItem.crawled_at.asc().nulls_last(),
                ContentItem.created_at.asc(),
                ContentItem.id.asc(),
            )
            .limit(max(1, limit))
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def list_historical_canonicals(
        self,
        *,
        owner_user_id: int | None,
        since: datetime,
        limit: int,
    ) -> list[HistoricalCanonical]:
        stmt = (
            select(ContentEventGroup, ContentItem)
            .join(
                ContentItem,
                ContentItem.id == ContentEventGroup.canonical_content_id,
            )
            .where(
                self._group_owner_clause(owner_user_id),
                self._owner_clause(owner_user_id),
                ContentEventGroup.status == EventStatus.ACTIVE,
                ContentEventGroup.last_occurrence_at >= since,
            )
            .order_by(
                ContentEventGroup.last_occurrence_at.desc(),
                ContentEventGroup.id.desc(),
            )
            .limit(max(1, limit))
        )
        result = await self.db.execute(stmt)
        return [HistoricalCanonical(event_group=row[0], content=row[1]) for row in result.all()]

    async def assigned_content_ids(self, content_ids: Sequence[int]) -> set[int]:
        ids = sorted({int(value) for value in content_ids})
        if not ids:
            return set()
        canonical_result = await self.db.execute(
            select(ContentEventGroup.canonical_content_id).where(ContentEventGroup.canonical_content_id.in_(ids))
        )
        member_result = await self.db.execute(
            select(ContentEventMember.content_id).where(ContentEventMember.content_id.in_(ids))
        )
        return {
            *[int(value) for value in canonical_result.scalars().all()],
            *[int(value) for value in member_result.scalars().all()],
        }
