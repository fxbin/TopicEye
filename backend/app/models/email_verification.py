"""邮箱验证码存储模型。

用于注册流程的邮箱验证，验证码以 sha256 哈希存储，支持过期与防重放。
"""
# author: fxbin

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EmailVerificationCode(Base):
    """邮箱验证码记录。

    每次发送验证码生成一条记录，校验通过后标记 used_at。
    code_hash 存储 sha256 哈希，不保留明文。
    attempts 记录错误尝试次数，超过阈值后失效。
    """

    __tablename__ = "email_verification_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    code_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
    )

    __table_args__ = (
        Index("ix_email_verification_email_created", "email", "created_at"),
    )
