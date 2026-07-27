"""
Repository for AppSetting model operations.

封装按 key 读写 AppSetting 的查询：
- 按 key 查询单条配置
- upsert by key（存在则更新 value/updated_at，不存在则插入新行）
- RSSHub 实例列表读写
- Feature flags 读写

不处理 commit，事务边界由调用方（service/endpoint）负责。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import select

from app.models.app_setting import (
    DEFAULT_FEATURE_FLAGS,
    DEFAULT_RSSHUB_INSTANCES,
    AppSetting,
)
from app.repositories.base import BaseRepository


class AppSettingRepository(BaseRepository[AppSetting]):
    """AppSetting CRUD（按 key 索引）。"""

    model = AppSetting

    async def get_by_key(self, key: str) -> AppSetting | None:
        """按 key 查询单条配置，不存在返回 None。"""
        result = await self.db.execute(select(AppSetting).where(AppSetting.key == key))
        return result.scalar_one_or_none()

    async def upsert_setting(
        self,
        key: str,
        value: str,
        description: str | None = None,
        *,
        existing: AppSetting | None = None,
    ) -> AppSetting:
        """按 key upsert 配置。不 commit，调用方负责事务边界。

        - existing 非 None 时跳过查询，直接复用调用方已查到的实例
          （避免在敏感字段保留逻辑中重复查询）
        - 存在则更新 value + updated_at，description 保持原值不变
        - 不存在则插入新行，description 仅在插入时生效

        返回写入后的 AppSetting 实例（已 attach 到 session）。
        """
        row = existing if existing is not None else await self.get_by_key(key)
        now = datetime.now(UTC)
        if row is not None:
            row.value = value
            row.updated_at = now
            return row
        new_row = AppSetting(
            key=key,
            value=value,
            description=description or "",
            updated_at=now,
        )
        self.db.add(new_row)
        return new_row

    # ── RSSHub 实例列表 ────────────────────────────────────────────────

    async def list_rsshub_instances(self) -> list[dict]:
        """返回按 priority 升序排列的已启用 RSSHub 实例列表。

        DB 为空或 JSON 损坏时回退 DEFAULT_RSSHUB_INSTANCES。
        """
        row = await self.get_by_key("rsshub_instances")
        if row and row.value:
            try:
                instances = json.loads(row.value)
                return sorted(
                    [i for i in instances if i.get("enabled", True)],
                    key=lambda x: x.get("priority", 0),
                )
            except json.JSONDecodeError:
                pass
        return list(DEFAULT_RSSHUB_INSTANCES)

    async def save_rsshub_instances(self, instances: list[dict]) -> None:
        """保存 RSSHub 实例列表到 DB。不 commit，调用方负责事务边界。"""
        await self.upsert_setting(
            "rsshub_instances",
            json.dumps(instances, ensure_ascii=False),
            description="RSSHub 实例列表，支持多实例降级",
        )

    # ── Feature flags ──────────────────────────────────────────────────

    async def list_feature_flags(self) -> dict[str, bool]:
        """读取全部 feature flags，DB 为空或损坏时回退 DEFAULT_FEATURE_FLAGS。

        与 DEFAULT 合并：DEFAULT 提供新增 key 的默认值，stored 覆盖已配置的。
        """
        row = await self.get_by_key("feature_flags")
        if row and row.value:
            try:
                stored = json.loads(row.value)
                if isinstance(stored, dict):
                    merged = {**DEFAULT_FEATURE_FLAGS}
                    merged.update({k: bool(v) for k, v in stored.items()})
                    return merged
            except (json.JSONDecodeError, TypeError):
                pass
        return dict(DEFAULT_FEATURE_FLAGS)

    async def get_feature_flag(self, key: str) -> bool:
        """单个 feature flag 查询。未知 key 回退 DEFAULT_FEATURE_FLAGS 的值或 False。"""
        flags = await self.list_feature_flags()
        return bool(flags.get(key, DEFAULT_FEATURE_FLAGS.get(key, False)))

    async def upsert_feature_flags(self, flags: dict[str, bool]) -> dict[str, bool]:
        """Upsert feature flags 到 DB，返回合并后的完整 flags。

        不 commit，调用方负责事务边界。
        """
        current = await self.list_feature_flags()
        current.update({k: bool(v) for k, v in flags.items()})
        await self.upsert_setting(
            "feature_flags",
            json.dumps(current, ensure_ascii=False),
            description="功能模块开关（管理员后台可控）",
        )
        return current
