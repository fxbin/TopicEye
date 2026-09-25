"""内容选题标注（排序效果基准的标注层）。

一条标注 = 一个 content 的「值得写 / 不值得 / 不确定」结论，按来源分三类：

- human      管理员人工标注（口径校准的地面真值，优先级最高）
- pick_mark  日报选题卡上的 write/watch/skip 导入（同样是人的判断）
- behavioral 行为信号推断的弱标注（收藏/反馈/成稿/忽略加权合成）

同一 content 只保留一行当前结论（unique content_id）；behavioral 刷新
不覆盖 human / pick_mark 行。权重与阈值见 services/ranking_eval.py。
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ContentLabelValue(enum.StrEnum):
    WORTH_WRITING = "worth_writing"
    NOT_WORTH = "not_worth"
    UNCERTAIN = "uncertain"


class ContentLabelSource(enum.StrEnum):
    HUMAN = "human"
    PICK_MARK = "pick_mark"
    BEHAVIORAL = "behavioral"


class ContentLabel(Base):
    __tablename__ = "content_labels"
    __table_args__ = (UniqueConstraint("content_id", name="uq_content_labels_content"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(20), nullable=False)  # worth_writing | not_worth | uncertain
    source: Mapped[str] = mapped_column(String(20), nullable=False)  # human | pick_mark | behavioral
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # 产生该结论的证据快照（如 {"favorite": 2, "feedback_like": 1}）
    evidence: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    labeled_by: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    content: Mapped[Any | None] = relationship("ContentItem")
