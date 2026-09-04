"""add llm_models.context_window

Revision ID: f5d8a2b6c9e0
Revises: e4a91c2f7b3d
Create Date: 2026-09-04

模型目录 V2：llm_models 加可空 context_window 列（模型目录预填或手填）。
供 provider 候选循环做调用前 fail-open 预检；空值行为与 V1 一致。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f5d8a2b6c9e0"
down_revision: str | None = "e4a91c2f7b3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "llm_models",
        sa.Column(
            "context_window",
            sa.Integer(),
            nullable=True,
            comment="上下文窗口 tokens（来自模型目录预填或手填；空=不做调用前预检）",
        ),
    )


def downgrade() -> None:
    op.drop_column("llm_models", "context_window")
