"""
App-level key/value settings, stored in DB for admin UI.
Currently used for: RSSHub instance list.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import String, Text, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppSetting(Base):
    """
    Simple key-value store for app-wide settings.

    Keys:
      - rsshub_instances: JSON list of {"url": "...", "enabled": true, "priority": 0}
    """

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    description: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# Default RSSHub public instances (used when DB is empty)
DEFAULT_RSSHUB_INSTANCES = [
    {"url": "https://rsshub.app", "enabled": True, "priority": 0, "note": "官方实例，已限制"},
    {"url": "https://rsshub.rssforever.com", "enabled": True, "priority": 1, "note": "社区实例"},
]


def get_rsshub_instances() -> list[dict]:
    """Return ordered list of enabled RSSHub instances from DB."""
    from app.core.database import async_session
    from sqlalchemy import select

    async def _get():
        async with async_session() as db:
            result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
            row = result.scalar_one_or_none()
            if row and row.value:
                try:
                    instances = json.loads(row.value)
                    return sorted([i for i in instances if i.get("enabled", True)], key=lambda x: x.get("priority", 0))
                except json.JSONDecodeError:
                    pass
            return DEFAULT_RSSHUB_INSTANCES

    import asyncio

    return asyncio.run(_get())


async def get_rsshub_instances_async(db=None) -> list[dict]:
    """Async version — returns ordered list of enabled RSSHub instances."""
    close_after = False
    if db is None:
        from app.core.database import async_session

        db = async_session()
        close_after = True

    try:
        result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
        row = result.scalar_one_or_none()
        if row and row.value:
            try:
                instances = json.loads(row.value)
                return sorted([i for i in instances if i.get("enabled", True)], key=lambda x: x.get("priority", 0))
            except json.JSONDecodeError:
                pass
        return DEFAULT_RSSHUB_INSTANCES
    finally:
        if close_after:
            await db.close()


async def save_rsshub_instances(instances: list[dict], db) -> None:
    """Save RSSHub instance list to DB."""
    setting = AppSetting(
        key="rsshub_instances",
        value=json.dumps(instances, ensure_ascii=False),
        description="RSSHub 实例列表，支持多实例降级",
    )
    db.add(setting)
    await db.flush()
