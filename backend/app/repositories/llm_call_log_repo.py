"""
Repository for LlmCallLog model operations.

服务于 /api/v1/metrics/llm-logs 端点，封装按状态过滤的最近调用查询。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LlmCallLog


class LlmCallLogRepository:
    """LlmCallLog 查询（非 BaseRepository 子类，因为只做投影查询）。

    Usage:
        repo = LlmCallLogRepository(db)
        rows = await repo.list_recent(status="FAILED", cutoff=cutoff, limit=50)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_recent(
        self,
        *,
        status: str | None = None,
        cutoff: datetime,
        limit: int = 50,
    ) -> Sequence[tuple]:
        """返回最近调用日志，按 created_at 倒序。

        返回元组字段顺序：
        (request_id, scene, actual_model, status, error_message,
         duration_ms, input_tokens, output_tokens, total_cost, created_at)

        Args:
            status: 过滤状态（DONE / FAILED），None 或 "ALL" 表示不过滤
            cutoff: 时间下限（含），仅返回 created_at >= cutoff 的记录
            limit: 最多返回条数
        """
        stmt = (
            select(
                LlmCallLog.request_id,
                LlmCallLog.scene,
                LlmCallLog.actual_model,
                LlmCallLog.status,
                LlmCallLog.error_message,
                LlmCallLog.duration_ms,
                LlmCallLog.input_tokens,
                LlmCallLog.output_tokens,
                LlmCallLog.total_cost,
                LlmCallLog.created_at,
            )
            .where(LlmCallLog.created_at >= cutoff)
            .order_by(desc(LlmCallLog.created_at))
            .limit(limit)
        )
        if status and status != "ALL":
            stmt = stmt.where(LlmCallLog.status == status.upper())

        result = await self.db.execute(stmt)
        return result.all()
