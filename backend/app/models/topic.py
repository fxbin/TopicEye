"""
Topic cluster model — groups related content items.
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from app.core.database import Base


class TopicGroup(Base):
    __tablename__ = "topic_groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False, comment="话题名称（LLM 生成）")
    keywords = Column(JSON, nullable=True, comment="关键标签列表")
    summary = Column(Text, nullable=True, comment="话题一句话摘要")
    content_count = Column(Integer, default=0, comment="话题下内容数")
    best_score = Column(Float, default=0.0, comment="话题内最高精选分")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC))

    __table_args__ = (
        # list_ordered_by_best_score() — ORDER BY best_score DESC
        Index("ix_topic_groups_best_score", best_score.desc()),
        # get_or_create(name) — WHERE name = ?
        Index("ix_topic_groups_name", "name"),
    )

    # Relationships
    items = relationship(
        "ContentItem",
        back_populates="topic",
        foreign_keys="ContentItem.topic_id",
    )
