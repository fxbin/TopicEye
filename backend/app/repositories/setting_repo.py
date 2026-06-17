"""
Repository for AppSetting — simple key/value store.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone, UTC
from typing import Optional

from sqlalchemy import select

from app.models.app_setting import AppSetting
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class SettingRepository(BaseRepository[AppSetting]):
    """AppSetting repository with convenience get/set by key."""

    model = AppSetting

    async def get_value(self, key: str) -> str | None:
        """Return the value for *key*, or None if not found."""
        stmt = select(self.model).where(self.model.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        return row.value if row else None

    async def set_value(self, key: str, value: str) -> AppSetting:
        """Upsert a setting row by key. Creates if missing, updates if present."""
        stmt = select(self.model).where(self.model.key == key)
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()

        if row is not None:
            row.value = value
            row.updated_at = datetime.now(UTC)
            await self.db.flush()
            await self.db.refresh(row)
            return row

        # Create new
        return await self.create(key=key, value=value)
