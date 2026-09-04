"""Model catalog ORM — models.dev 开放目录的本地缓存表。

参考数据（reference data），与用户运行时配置 ``llm_models`` 完全解耦：
- 本表只由「启动快照 seed」和「每日刷新 job」写入，API 只读；
- 价格/上下文窗口等元数据仅用于管理端表单预填与展示，
  永不写回 ``llm_models``，不影响运行时路由与计费。
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
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ModelCatalogModel(Base):
    __tablename__ = "model_catalog_models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="models.dev provider id，如 zhipuai / deepseek / openrouter"
    )
    model_id: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="models.dev 模型 id（裸名，不含 provider 前缀）"
    )
    name: Mapped[str | None] = mapped_column(String(200), nullable=True, comment="模型显示名")
    context_window: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="上下文窗口 tokens")
    max_output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="最大输出 tokens")
    cost_per_1m_input: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="每1M input token 价格（目录原值）"
    )
    cost_per_1m_output: Mapped[float | None] = mapped_column(Float, nullable=True, comment="每1M output token 价格")
    cost_per_1m_cache_read: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="每1M cache read token 价格"
    )
    supports_tool_call: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supports_structured_output: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    supports_reasoning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    input_modalities: Mapped[None | list] = mapped_column(JSON, nullable=True, comment='如 ["text","image"]')
    output_modalities: Mapped[None | list] = mapped_column(JSON, nullable=True)
    open_weights: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    status: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="目录状态，如 beta / deprecated")
    release_date: Mapped[str | None] = mapped_column(String(20), nullable=True)
    last_updated: Mapped[str | None] = mapped_column(String(20), nullable=True, comment="目录侧最后更新日期")
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), comment="本条数据写入批次时间"
    )

    __table_args__ = (
        UniqueConstraint("provider", "model_id", name="uq_model_catalog_provider_model"),
        Index("ix_model_catalog_provider", "provider"),
    )

    def __repr__(self) -> str:
        return f"<ModelCatalogModel {self.provider}/{self.model_id}>"
