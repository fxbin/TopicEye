"""
LLM model configuration & evaluation models.

Tables:
  - llm_models: model provider configs (name, model_id, api_key, base_url, enabled, is_default …)
  - model_evaluations: A/B test results for each model on eval prompts
  - llm_call_logs: request-level token and cost logs for model calls
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LlmModel(Base):
    __tablename__ = "llm_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, comment="显示名称，如 GLM-5.1")
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="litellm provider: openai / custom_zhipu …"
    )
    model_id: Mapped[str] = mapped_column(String(200), nullable=False, comment="litellm model string: openai/glm-5.1")
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="API Key (加密存储)")
    api_base: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="自定义 API endpoint")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    routing_group: Mapped[str] = mapped_column(String(50), default="default", nullable=False, comment="运行时路由组")
    model_family: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="模型家族，如 deepseek/qwen/glm"
    )
    channel_name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="渠道名，如 official/opencode/openrouter"
    )
    routing_priority: Mapped[int] = mapped_column(
        Integer, default=100, nullable=False, comment="路由优先级，数字越小越先尝试"
    )
    cooldown_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False, comment="失败后冷却秒数")
    temperature: Mapped[float] = mapped_column(Float, default=0.3, nullable=False)
    max_tokens: Mapped[int] = mapped_column(Integer, default=2000, nullable=False)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=30, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_per_1k_input: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="每1k input token 成本(元)"
    )
    cost_per_1k_output: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="每1k output token 成本(元)"
    )
    extra_params: Mapped[str | None] = mapped_column(JSON, nullable=True, comment="额外参数(JSON)")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), onupdate=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_llm_models_enabled", "enabled"),
        Index("ix_llm_models_route", "routing_group", "routing_priority"),
    )

    def __repr__(self) -> str:
        return f"<LlmModel {self.name} ({self.model_id})>"


class ModelEvaluation(Base):
    __tablename__ = "model_evaluations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    eval_run_id: Mapped[str] = mapped_column(String(50), nullable=False, index=True, comment="测评批次ID")
    model_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True, comment="关联 llm_models.id")
    model_name: Mapped[str] = mapped_column(String(100), nullable=False, comment="快照模型名")
    prompt_type: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="测评类型: analysis/daily_report/weekly_digest/classification"
    )
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="使用的 prompt (可选存储)")
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True, comment="模型输出")
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="响应耗时(毫秒)")
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输入 token 数")
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="输出 token 数")
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="人工打分 1-5")
    auto_score: Mapped[float | None] = mapped_column(Float, nullable=True, comment="自动评分")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True, comment="人工备注")
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING", comment="PENDING/RUNNING/DONE/FAILED"
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (Index("ix_model_evals_run_type", "eval_run_id", "prompt_type"),)

    def __repr__(self) -> str:
        return f"<ModelEvaluation {self.model_name} {self.prompt_type} {self.status}>"


class LlmCallLog(Base):
    __tablename__ = "llm_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    model_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    request_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actual_model: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scene: Mapped[str] = mapped_column(String(50), nullable=False, default="general", index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DONE", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cache_creation_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    billable_input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    output_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cache_read_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cache_creation_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cost_per_1m_input: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_1m_output: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_1m_input_cache_hit: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_1m_input_cache_create: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), index=True
    )

    __table_args__ = (
        Index("ix_llm_call_logs_model_created", "model_id", "created_at"),
        Index("ix_llm_call_logs_scene_created", "scene", "created_at"),
    )

    def __repr__(self) -> str:
        return f"<LlmCallLog {self.request_id} {self.actual_model or self.request_model} {self.status}>"
