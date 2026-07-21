"""
Repository for LlmModel model operations.

封装 LlmModel 配置的 CRUD 与 LlmCallLog + LlmModel JOIN 聚合查询：
- 列表查询（按 routing_group / routing_priority / id 排序）
- 按 id 查询单条配置
- LlmCallLog + LlmModel JOIN 查询（用于 token 用量汇总）

LlmCallLog 的简单投影查询由 LlmCallLogRepository 负责，本 repo 只负责
LlmModel 主表 CRUD 和需要 JOIN 的聚合查询。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import LlmCallLog, LlmModel
from app.repositories.base import BaseRepository


class LlmModelRepository(BaseRepository[LlmModel]):
    """LlmModel 配置 CRUD + 与 LlmCallLog 的 JOIN 聚合查询。"""

    model = LlmModel

    async def list_ordered_for_api(self) -> Sequence[LlmModel]:
        """返回全部 LlmModel 配置，按 routing_group / routing_priority / id 排序。

        与 /models 端点历史行为等价，用于前端模型列表渲染。
        """
        stmt = (
            select(LlmModel)
            .order_by(LlmModel.routing_group, LlmModel.routing_priority, LlmModel.id)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    def add_instance(self, model: LlmModel) -> None:
        """将外部已构造的 LlmModel 实例加入 session。

        供 create_model 端点使用：那里由 _new_model_from_request 完成字段加工
        （含 pricing 计算与 free_model 归零），repo 只负责持久化。不 flush，
        调用方负责事务边界。
        """
        self.db.add(model)

    async def delete_instance(self, model: LlmModel) -> None:
        """删除已加载的 LlmModel 实例并 flush。

        供 delete_model 端点使用，与 add_instance 对称。
        """
        await self.db.delete(model)
        await self.db.flush()

    async def list_enabled_by_ids(self, model_ids: list[int]) -> Sequence[LlmModel]:
        """按 id 列表查询已启用的 LlmModel，用于 A/B 测评选择参与模型。

        返回顺序不保证，调用方需自行处理。与 run_evaluation 端点历史行为等价。
        """
        stmt = select(LlmModel).where(
            LlmModel.id.in_(model_ids),
            LlmModel.enabled == True,  # noqa: E712
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_call_logs_with_model_since(
        self,
        *,
        since: datetime,
    ) -> Sequence[tuple]:
        """返回 created_at >= since 的 LlmCallLog + LlmModel JOIN 结果。

        返回元组：(LlmCallLog, LlmModel | None)，按 LlmCallLog.created_at DESC 排序。
        LlmModel 用 left join，未匹配时为 None（兼容日志中残留的已删除 model_id）。

        用于 /models/usage/summary 端点按模型/按 prompt 聚合 token 用量与成本。
        """
        stmt = (
            select(LlmCallLog, LlmModel)
            .join(LlmModel, LlmCallLog.model_id == LlmModel.id, isouter=True)
            .where(LlmCallLog.created_at >= since)
            .order_by(desc(LlmCallLog.created_at))
        )
        result = await self.db.execute(stmt)
        return result.all()
