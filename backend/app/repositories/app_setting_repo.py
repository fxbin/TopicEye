"""
Repository for AppSetting model operations.

封装按 key 读写 AppSetting 的查询：
- 按 key 查询单条配置
- upsert by key（存在则更新 value/updated_at，不存在则插入新行）

不处理 commit，事务边界由调用方（service/endpoint）负责。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
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
