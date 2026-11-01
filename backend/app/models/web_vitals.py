"""前端体验指标样本模型（#179）。

一条记录 = 浏览器侧 web-vitals 的一次观测（LCP / INP / CLS / FCP / TTFB 之一）。

设计取舍：

- ``path`` 存**归一化后的路由模板**（如 ``/topics/[id]``），不是原始 pathname。
  归一在 service 层做（唯一真源），避免内容 id 把路径基数撑爆。
- 不存原始 User-Agent，只存派生的 ``device_class``，够做 p75 分层且不留可识别信息。
- ``rating`` 由服务端按自己的阈值算，不采信客户端上报值。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WebVitalSample(Base):
    """单条前端体验指标样本。"""

    __tablename__ = "web_vitals_samples"
    __table_args__ = (
        CheckConstraint(
            "metric IN ('LCP', 'INP', 'CLS', 'FCP', 'TTFB')",
            name="ck_web_vitals_samples_metric",
        ),
        CheckConstraint(
            "rating IN ('good', 'needs-improvement', 'poor')",
            name="ck_web_vitals_samples_rating",
        ),
        CheckConstraint(
            "device_class IN ('mobile', 'desktop', 'tablet', 'unknown')",
            name="ck_web_vitals_samples_device_class",
        ),
        Index("ix_web_vitals_samples_metric_captured_at", "metric", "captured_at"),
        Index("ix_web_vitals_samples_path_captured_at", "path", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        index=True,
    )
    # 归一化后的路由模板（如 /topics/[id]）
    path: Mapped[str] = mapped_column(String(200), nullable=False)
    metric: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    # 服务端按阈值判定：good | needs-improvement | poor
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    navigation_type: Mapped[str] = mapped_column(String(20), nullable=False, default="navigate")
    device_class: Mapped[str] = mapped_column(String(10), nullable=False, default="unknown")
    # 未登录上报时为空；用户注销后置空而非级联删除样本
    user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    def __repr__(self) -> str:
        return f"<WebVitalSample {self.metric}={self.value} path={self.path}>"
