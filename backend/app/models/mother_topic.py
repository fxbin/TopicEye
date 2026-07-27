"""
MotherTopic — 公众号母题配置。

每个母题包含：名称、关键词列表、权重、内容类型、目标读者。
系统根据关键词匹配内容，自动打上母题标签。

多租户模型（路线 C：系统模板库 + 用户 fork）：
- owner_user_id IS NULL  → 系统模板，admin 维护，用户只读
- owner_user_id = <uid>   → 用户私有 fork，用户可自由改/加/停用
新用户首次访问 /my-topics 时由应用层 fork_default_templates_for_user
懒触发复制一份系统模板到用户名下。
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ContentType(enum.StrEnum):
    """内容类型枚举，描述该母题适合产出的内容形式。"""

    TOOL_REVIEW = "工具评测"  # AI工具/软件/硬件评测
    METHODOLOGY = "方法论"  # 经验总结/工作流/方法论
    OBSERVATION = "观察"  # 时代观察/趋势分析
    PERSONAL = "随笔"  # 个人思考/记录/生活
    TUTORIAL = "教程"  # 教程/教学/科普
    OPINION = "观点"  # 观点输出/评论


class MotherTopic(Base):
    """母题配置表。"""

    __tablename__ = "mother_topics"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String(200), nullable=True)
    keywords: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # keywords 示例: ["AI工具", "ChatGPT", "工作流", "效率", "Notion"]
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    # weight: 母题权重乘数，影响最终选题打分
    content_type: Mapped[str] = mapped_column(String(20), nullable=True)
    # content_type: ContentType 枚举值
    target_reader: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # target_reader: 目标读者描述，如"对效率提升有兴趣的创作者"
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    display_order: Mapped[int] = mapped_column(nullable=False, default=0)
    # display_order: 排列顺序，数字越小越靠前
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        nullable=True,
        index=True,
        comment="NULL=系统模板；非 NULL=用户自定义 fork",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    def match_score(self, text: str) -> float:
        """
        计算一段文本与本母题的匹配得分。
        返回 0.0 ~ 1.0，1.0 = 高度匹配。
        """
        if not text or not self.keywords:
            return 0.0

        text_lower = text.lower()
        matched = sum(1 for kw in self.keywords if kw.lower() in text_lower)
        if not matched:
            return 0.0

        # 归一化：匹配1个=0.3，2个=0.6，3个+=1.0
        return min(1.0, matched * 0.3 + (0.0 if matched < 2 else 0.1 * (matched - 2)))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "keywords": self.keywords,
            "weight": self.weight,
            "content_type": self.content_type,
            "target_reader": self.target_reader,
            "is_active": self.is_active,
            "display_order": self.display_order,
            "owner_user_id": self.owner_user_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:
        return f"<MotherTopic {self.name} weight={self.weight}>"
