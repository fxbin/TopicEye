"""add model_catalog_models table

Revision ID: e4a91c2f7b3d
Revises: c003bd551911
Create Date: 2026-09-04

models.dev 模型目录本地缓存表（参考数据，与 llm_models 运行时配置解耦）。
由启动快照 seed 与每日刷新 job 写入，API 只读。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4a91c2f7b3d"
down_revision: str | None = "c003bd551911"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_catalog_models",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "provider",
            sa.String(length=50),
            nullable=False,
            comment="models.dev provider id，如 zhipuai / deepseek / openrouter",
        ),
        sa.Column(
            "model_id", sa.String(length=200), nullable=False, comment="models.dev 模型 id（裸名，不含 provider 前缀）"
        ),
        sa.Column("name", sa.String(length=200), nullable=True, comment="模型显示名"),
        sa.Column("context_window", sa.Integer(), nullable=True, comment="上下文窗口 tokens"),
        sa.Column("max_output_tokens", sa.Integer(), nullable=True, comment="最大输出 tokens"),
        sa.Column("cost_per_1m_input", sa.Float(), nullable=True, comment="每1M input token 价格（目录原值）"),
        sa.Column("cost_per_1m_output", sa.Float(), nullable=True, comment="每1M output token 价格"),
        sa.Column("cost_per_1m_cache_read", sa.Float(), nullable=True, comment="每1M cache read token 价格"),
        sa.Column("supports_tool_call", sa.Boolean(), nullable=True),
        sa.Column("supports_structured_output", sa.Boolean(), nullable=True),
        sa.Column("supports_reasoning", sa.Boolean(), nullable=True),
        sa.Column("input_modalities", sa.JSON(), nullable=True, comment='如 ["text","image"]'),
        sa.Column("output_modalities", sa.JSON(), nullable=True),
        sa.Column("open_weights", sa.Boolean(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=True, comment="目录状态，如 beta / deprecated"),
        sa.Column("release_date", sa.String(length=20), nullable=True),
        sa.Column("last_updated", sa.String(length=20), nullable=True, comment="目录侧最后更新日期"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False, comment="本条数据写入批次时间"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_model_catalog_models")),
        sa.UniqueConstraint("provider", "model_id", name="uq_model_catalog_provider_model"),
    )
    op.create_index("ix_model_catalog_provider", "model_catalog_models", ["provider"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_model_catalog_provider", table_name="model_catalog_models")
    op.drop_table("model_catalog_models")
