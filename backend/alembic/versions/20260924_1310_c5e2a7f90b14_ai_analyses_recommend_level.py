"""ai_analyses 持久化推荐等级

Revision ID: c5e2a7f90b14
Revises: a3f8c2d94e17
Create Date: 2026-09-24

推荐等级此前只在前端由 explainRecommendation 即时计算，服务端无法
按等级筛选内容列表。本迁移在 ai_analyses 上增加可空 recommend_level
列：新分析写入时由统一分类器（services/recommendation_level.py）判定
填充；存量行用 backend/scripts/backfill_recommend_level.py 回填，
未回填前为 NULL（前端继续用本地规则兜底展示）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5e2a7f90b14"
down_revision: str | None = "a3f8c2d94e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ai_analyses",
        sa.Column(
            "recommend_level",
            sa.String(length=30),
            nullable=True,
            comment="推荐等级（写入时按统一门槛判定，见 services/recommendation_level.py）",
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_analyses", "recommend_level")
