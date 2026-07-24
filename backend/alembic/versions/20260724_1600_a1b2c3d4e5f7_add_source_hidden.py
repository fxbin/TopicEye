"""add hidden column to sources

Revision ID: a1b2c3d4e5f7
Revises: e1a2b3c4d5f6
Create Date: 2026-07-24 16:00:00

``hidden=True`` 的信源（如微信读书自动创建的虚拟信源）对用户不可见、
不计入私有信源配额、不被批量同步调度器选中。数据链路上 Source 行照常
存在，ContentItem.source_id 关联不受影响。
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f7"
down_revision = "e1a2b3c4d5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "hidden",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment="True=系统自动创建的信源，对用户不可见且不计入配额",
            )
        )

    # Mark existing WeRead auto-created sources as hidden
    op.execute(
        "UPDATE sources SET hidden = true WHERE url = 'https://weread.qq.com/r/weread-skills'"
    )


def downgrade() -> None:
    with op.batch_alter_table("sources", schema=None) as batch_op:
        batch_op.drop_column("hidden")
