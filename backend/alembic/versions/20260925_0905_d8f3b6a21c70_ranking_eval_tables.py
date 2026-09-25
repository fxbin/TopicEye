"""排序效果基准：标注表 + 快照表

Revision ID: d8f3b6a21c70
Revises: c5e2a7f90b14
Create Date: 2026-09-25

排序效果此前没有度量层：调权重只能看分数外观。本迁移建立两张表：

- content_labels        内容级「值得写」标注（human / pick_mark / behavioral
  三来源，behavioral 由行为信号加权推断并可用
  scripts/backfill_content_labels.py 回填存量）
- ranking_eval_snapshots 按时间窗物化的评测结果 + 当时评分配置快照，
  供 scripts/run_ranking_baseline.py 与 /admin/ranking-eval 使用
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d8f3b6a21c70"
down_revision: str | None = "c5e2a7f90b14"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "content_labels",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "content_id",
            sa.Integer(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("label", sa.String(length=20), nullable=False, comment="worth_writing | not_worth | uncertain"),
        sa.Column("source", sa.String(length=20), nullable=False, comment="human | pick_mark | behavioral"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("evidence", sa.JSON(), nullable=True, comment="产生该结论的证据快照"),
        sa.Column("labeled_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("content_id", name="uq_content_labels_content"),
    )
    op.create_index("ix_content_labels_content_id", "content_labels", ["content_id"])

    op.create_table(
        "ranking_eval_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("surface", sa.String(length=50), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("scoring_config", sa.JSON(), nullable=True),
        sa.Column("item_details", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("surface", "window_start", name="uq_eval_surface_window"),
    )


def downgrade() -> None:
    op.drop_table("ranking_eval_snapshots")
    op.drop_index("ix_content_labels_content_id", table_name="content_labels")
    op.drop_table("content_labels")
