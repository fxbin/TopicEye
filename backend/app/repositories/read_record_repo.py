"""ReadRecord Repository.

封装用户阅读记录的 ORM 操作。业务逻辑（depth 派生、快照填充、保留期清理）
留在 service 层；本 repo 只负责纯粹的 CRUD + 按 (user, target) 范围查询。

upsert 事务边界：find_existing + merge_session / add_new 只 flush，
commit 由调用方（api 层的 get_db 依赖）控制。
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.read_record import ReadRecord, ReadTargetType
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class ReadRecordRepository(BaseRepository[ReadRecord]):
    """ReadRecord repository，按 (user_id, target_type, target_key) 三元组管理阅读记录。"""

    model = ReadRecord

    def __init__(self, db: AsyncSession):
        super().__init__(db)

    async def find_existing(
        self,
        user_id: int,
        target_type: ReadTargetType,
        target_key: str,
    ) -> ReadRecord | None:
        """按 (user, target_type, target_key) 唯一键查现有记录，供 upsert 使用。"""
        stmt = select(self.model).where(
            self.model.user_id == user_id,
            self.model.target_type == target_type,
            self.model.target_key == target_key,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(
        self,
        user_id: int,
        target_type: ReadTargetType | None = None,
        limit: int = 100,
    ) -> Sequence[ReadRecord]:
        """按用户查阅读历史；可选按报告类型过滤。排序：last_read_at DESC。"""
        stmt = select(self.model).where(self.model.user_id == user_id)
        if target_type is not None:
            stmt = stmt.where(self.model.target_type == target_type)
        stmt = stmt.order_by(self.model.last_read_at.desc()).limit(limit)
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def merge_session(
        self,
        record: ReadRecord,
        *,
        duration_ms: int,
        topic_keywords: list[str] | None = None,
        category: str | None = None,
    ) -> ReadRecord:
        """累加一次阅读会话到已有记录：read_count+1、累加时长、刷新 last_read_at。

        快照字段（topic_keywords/category）仅当传入非空且原值为空时回填，
        避免覆盖已有快照（首读快照最可信）。
        """
        record.read_count += 1
        record.accumulated_ms += duration_ms
        record.last_read_at = datetime.now(UTC)
        if topic_keywords and not record.topic_keywords:
            record.topic_keywords = topic_keywords
        if category and not record.category:
            record.category = category
        await self.db.flush()
        await self.db.refresh(record)
        return record

    def add_new(
        self,
        *,
        user_id: int,
        target_type: ReadTargetType,
        target_key: str,
        target_id: int | None = None,
        duration_ms: int = 0,
        topic_keywords: list[str] | None = None,
        category: str | None = None,
    ) -> ReadRecord:
        """创建并 db.add 一个新阅读记录，返回实例引用（不 flush/refresh）。

        供 service 层 upsert 使用——service 不直接 import ORM 模型类，
        也不直接 db.add。事务边界（db.commit）由 api 层 get_db 依赖控制。
        """
        record = self.model(
            user_id=user_id,
            target_type=target_type,
            target_key=target_key,
            target_id=target_id,
            read_count=1,
            accumulated_ms=duration_ms,
            topic_keywords=topic_keywords,
            category=category,
        )
        self.db.add(record)
        return record

    async def delete_older_than(self, cutoff: datetime) -> int:
        """删除 last_read_at 早于 cutoff 的记录（保留期清理），返回受影响行数。"""
        stmt = delete(self.model).where(self.model.last_read_at < cutoff)
        result = await self.db.execute(stmt)
        return result.rowcount or 0
