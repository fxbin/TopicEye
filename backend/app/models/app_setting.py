"""
App-level key/value settings, stored in DB for admin UI.
Currently used for: RSSHub instance list + feature flags.

本模块只保留 ORM 声明和领域常量。
DB 读写逻辑已下沉到 app/repositories/app_setting_repo.py。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppSetting(Base):
    """
    Simple key-value store for app-wide settings.

    Keys:
      - rsshub_instances: JSON list of {"url": "...", "enabled": true, "priority": 0}
      - feature_flags: JSON dict of {"module_key": bool}
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

# ── Feature flags (功能模块开关，管理员后台可控) ──────────────────────

# 默认值：开源用户 clone 后所有可选模块默认关闭，管理员后台按需开启。
# 新增模块开关时在此追加 key + 默认值。
DEFAULT_FEATURE_FLAGS: dict[str, bool] = {
    "webnovel_module": False,
}
