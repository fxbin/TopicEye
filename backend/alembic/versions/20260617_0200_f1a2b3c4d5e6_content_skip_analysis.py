"""content_items skip_analysis + skip_reason

Revision ID: f1a2b3c4d5e6
Revises: a7c3b9d2e4f6
Create Date: 2026-06-17 02:00:00

LLM 规则过滤层（参照 content-signal-radar lowSignalPenalty 设计）：
- skip_analysis: True 时不进 LLM 队列（claim_pending 过滤），
  但内容仍入库保留（不丢失信号）
- skip_reason: 跳过原因（hard_low_signal / short_text / self_promo）
- 索引 skip_analysis：claim_pending SQL 频繁过滤
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f1a2b3c4d5e6"
down_revision = "c9e5d2f8a3b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("content_items", schema=None) as batch_op:
        # PostgreSQL is strict about boolean defaults: literal `0` is an int and
        # fails with "column ... is of type boolean but default expression is of
        # type integer". `false` is the portable boolean literal across SQLite
        # and PostgreSQL.
        batch_op.add_column(
            sa.Column(
                "skip_analysis",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment="True 时不进 LLM 队列（参照 content-signal-radar lowSignalPenalty）",
            )
        )
        batch_op.add_column(
            sa.Column(
                "skip_reason",
                sa.String(length=200),
                nullable=True,
                comment="跳过原因：hard_low_signal / short_text / self_promo / etc",
            )
        )
        batch_op.create_index(
            batch_op.f("ix_content_items_skip_analysis"), ["skip_analysis"]
        )


def downgrade() -> None:
    with op.batch_alter_table("content_items", schema=None) as batch_op:
        batch_op.drop_index("ix_content_items_skip_analysis")
        batch_op.drop_column("skip_reason")
        batch_op.drop_column("skip_analysis")
