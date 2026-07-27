"""
Repository for ModelEvaluation model operations.

封装 LLM A/B 测评子系统的查询：
- 按 id 查询单条测评记录
- 按 eval_run_id 查询测评列表
- 测评运行列表聚合（按 run_id 分组的统计）
- 添加测评记录到 session

ModelEvaluation 与 LlmModel 同属 llm_model 模块，但查询逻辑独立，
单独建 repo 避免与 LlmModelRepository 混淆。
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Integer as SAInteger, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.llm_model import ModelEvaluation


class ModelEvaluationRepository:
    """ModelEvaluation 查询（非 BaseRepository 子类，含聚合查询）。

    Usage:
        repo = ModelEvaluationRepository(db)
        evaluation = await repo.get_by_id(eval_id)
    """

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, eval_id: int) -> ModelEvaluation | None:
        """按 id 查询单条测评记录，不存在返回 None。"""
        stmt = select(ModelEvaluation).where(ModelEvaluation.id == eval_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_run_id(self, run_id: str) -> Sequence[ModelEvaluation]:
        """按 eval_run_id 查询测评列表，按 model_name 排序。

        用于 get_eval_run 端点展示单个 run 的全部结果。
        """
        stmt = (
            select(ModelEvaluation)
            .where(ModelEvaluation.eval_run_id == run_id)
            .order_by(ModelEvaluation.model_name)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def aggregate_runs_with_stats(
        self,
        *,
        limit: int = 20,
    ) -> Sequence[tuple]:
        """按 eval_run_id + prompt_type 分组返回 run 统计，按 created_at 倒序。

        返回元组：(eval_run_id, prompt_type, model_count, created_at, done_count, fail_count)。
        用于 list_eval_runs 端点展示 run 列表。
        """
        stmt = (
            select(
                ModelEvaluation.eval_run_id,
                ModelEvaluation.prompt_type,
                func.count(ModelEvaluation.id).label("model_count"),
                func.min(ModelEvaluation.created_at).label("created_at"),
                func.sum(func.cast(ModelEvaluation.status == "DONE", SAInteger)).label("done_count"),
                func.sum(func.cast(ModelEvaluation.status == "FAILED", SAInteger)).label("fail_count"),
            )
            .group_by(ModelEvaluation.eval_run_id, ModelEvaluation.prompt_type)
            .order_by(desc(func.min(ModelEvaluation.created_at)))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return result.all()

    def add_instance(self, evaluation: ModelEvaluation) -> None:
        """将外部已构造的 ModelEvaluation 实例加入 session。

        供 run_evaluation 端点在循环里批量创建测评记录使用。不 flush，
        调用方负责事务边界。
        """
        self.db.add(evaluation)
