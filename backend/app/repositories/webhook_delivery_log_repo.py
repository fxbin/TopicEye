"""Repository for webhook delivery logs."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.webhook_delivery_log import WebhookDeliveryLog
from app.repositories.base import BaseRepository


class WebhookDeliveryLogRepository(BaseRepository[WebhookDeliveryLog]):
    """Read access to webhook delivery history."""

    model = WebhookDeliveryLog

    async def list_recent(
        self,
        *,
        event_type: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[Sequence[WebhookDeliveryLog], int]:
        """Return (logs newest-first, total_count), optionally filtered by event type."""
        stmt = select(WebhookDeliveryLog).order_by(
            WebhookDeliveryLog.created_at.desc()
        )
        count_stmt = select(func.count()).select_from(WebhookDeliveryLog)

        if event_type:
            stmt = stmt.where(WebhookDeliveryLog.event_type == event_type)
            count_stmt = count_stmt.where(WebhookDeliveryLog.event_type == event_type)

        stmt = stmt.offset(offset).limit(limit)

        result = await self.db.execute(stmt)
        logs = result.scalars().all()
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0
        return logs, total
