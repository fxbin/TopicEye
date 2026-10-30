from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class MuteRule(Base):
    """用户自定义降噪规则（#171）：命中的内容只对该用户的列表/精选默认排除。

    匹配语义（见 mute_rule_service）：

    - ``keyword`` → ``value`` 对 title/summary 大小写不敏感包含；
    - ``source``  → ``value`` 为信源 ID 的字符串形式，与 ``source_id`` 精确等值；
    - ``domain``  → ``value`` 已归一（小写、去 ``www.`` 前缀），与内容 url 的
      host 等值比较。
    """

    __tablename__ = "mute_rules"
    __table_args__ = (
        UniqueConstraint("user_id", "rule_type", "value", name="uq_mute_rules_user_type_value"),
        CheckConstraint("rule_type IN ('keyword', 'source', 'domain')", name="ck_mute_rules_rule_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # index=True 与迁移 ix_mute_rules_user_id 对齐（按用户读规则是消费链路热路径）
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rule_type: Mapped[str] = mapped_column(String(16), nullable=False)  # keyword | source | domain
    value: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
