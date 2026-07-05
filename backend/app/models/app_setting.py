"""
App-level key/value settings, stored in DB for admin UI.
Currently used for: RSSHub instance list.
"""

from __future__ import annotations
import json
from datetime import datetime, timezone, UTC
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
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
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


# ── Feature flags (功能模块开关，管理员后台可控) ──────────────────────

# 默认值：开源用户 clone 后所有可选模块默认关闭，管理员后台按需开启。
# 新增模块开关时在此追加 key + 默认值。
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "webnovel_module": False,  # 网文雷达（番茄/七猫/知乎盐选等国内网文榜单）
}


async def get_feature_flags_async(db=None) -> dict[str, bool]:
    """读取全部 feature flags，DB 为空或损坏时回退 DEFAULT_FEATURE_FLAGS。"""
    close_after = False
    if db is None:
        from app.core.database import async_session

        db = async_session()
        close_after = True
    try:
        result = await db.execute(select(AppSetting).where(AppSetting.key == "feature_flags"))
        row = result.scalar_one_or_none()
        if row and row.value:
            try:
                stored = json.loads(row.value)
                if isinstance(stored, dict):
                    # 与 DEFAULT 合并：DEFAULT 提供新增 key 的默认值，stored 覆盖已配置的
                    merged = {**DEFAULT_FEATURE_FLAGS}
                    merged.update({k: bool(v) for k, v in stored.items()})
                    return merged
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_FEATURE_FLAGS)
    finally:
        if close_after:
            await db.close()


async def get_feature_flag_async(db, key: str) -> bool:
    """单个 feature flag 查询。未知 key 回退 DEFAULT_FEATURE_FLAGS 的值或 False。"""
    flags = await get_feature_flags_async(db)
    return bool(flags.get(key, DEFAULT_FEATURE_FLAGS.get(key, False)))


async def set_feature_flags_async(flags: dict[str, bool], db) -> dict[str, bool]:
    """Upsert feature flags 到 DB。返回合并后的完整 flags。"""
    current = await get_feature_flags_async(db)
    current.update({k: bool(v) for k, v in flags.items()})
    raw_value = json.dumps(current, ensure_ascii=False)

    result = await db.execute(select(AppSetting).where(AppSetting.key == "feature_flags"))
    existing = result.scalar_one_or_none()
    if existing:
        existing.value = raw_value
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            AppSetting(
                key="feature_flags",
                value=raw_value,
                description="功能模块开关（管理员后台可控）",
            )
        )
    await db.flush()
    return current
