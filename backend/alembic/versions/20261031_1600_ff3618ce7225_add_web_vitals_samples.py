"""前端体验指标样本表 web_vitals_samples

Revision ID: ff3618ce7225
Revises: d2b7f9a41c05
Create Date: 2026-10-31

#179 前端体验指标接入系统内监控面：浏览器侧 web-vitals 上报的单次观测落库。

- 一行 = 一个指标的一次观测（LCP / INP / CLS / FCP / TTFB 之一）。
- path 存**归一化后的路由模板**（如 /topics/[id]），不是原始 pathname，
  避免内容 id 把路径基数撑爆；归一规则在 service 层（唯一真源）。
- rating 由服务端按自己的阈值算（不采信客户端上报值），
  与 web-vitals v5 的判定语义一致。
- 不存原始 User-Agent，只存派生的 device_class。
- user_id 可空：未登录上报时为空；用户注销后置空而非级联删除样本。
- 纯增量新表（无数据回填、不改既有表），downgrade 直接删表。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ff3618ce7225"
down_revision: str | None = "d2b7f9a41c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "web_vitals_samples"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            comment="样本采集时刻",
        ),
        sa.Column(
            "path",
            sa.String(length=200),
            nullable=False,
            comment="归一化后的路由模板（如 /topics/[id]）",
        ),
        sa.Column(
            "metric",
            sa.String(length=16),
            nullable=False,
            comment="LCP | INP | CLS | FCP | TTFB",
        ),
        sa.Column(
            "value",
            sa.Float(),
            nullable=False,
            comment="指标原值：毫秒（CLS 为无量纲分值）",
        ),
        sa.Column(
            "rating",
            sa.String(length=20),
            nullable=False,
            comment="服务端判定的档位：good | needs-improvement | poor",
        ),
        sa.Column(
            "navigation_type",
            sa.String(length=20),
            nullable=False,
            comment="navigate | reload | back-forward | soft-navigation 等",
        ),
        sa.Column(
            "device_class",
            sa.String(length=10),
            nullable=False,
            comment="派生的设备类型：mobile | desktop | tablet | unknown",
        ),
        sa.Column(
            "user_id",
            sa.Integer(),
            nullable=True,
            comment="上报用户，未登录为空",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "metric IN ('LCP', 'INP', 'CLS', 'FCP', 'TTFB')",
            name="ck_web_vitals_samples_metric",
        ),
        sa.CheckConstraint(
            "rating IN ('good', 'needs-improvement', 'poor')",
            name="ck_web_vitals_samples_rating",
        ),
        sa.CheckConstraint(
            "device_class IN ('mobile', 'desktop', 'tablet', 'unknown')",
            name="ck_web_vitals_samples_device_class",
        ),
    )
    op.create_index("ix_web_vitals_samples_captured_at", _TABLE, ["captured_at"])
    op.create_index("ix_web_vitals_samples_metric_captured_at", _TABLE, ["metric", "captured_at"])
    op.create_index("ix_web_vitals_samples_path_captured_at", _TABLE, ["path", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_web_vitals_samples_path_captured_at", table_name=_TABLE)
    op.drop_index("ix_web_vitals_samples_metric_captured_at", table_name=_TABLE)
    op.drop_index("ix_web_vitals_samples_captured_at", table_name=_TABLE)
    op.drop_table(_TABLE)
