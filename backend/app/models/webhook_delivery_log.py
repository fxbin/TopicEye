"""Webhook delivery log model — records each webhook push attempt."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class WebhookDeliveryLog(Base):
    """A single webhook delivery attempt (one per webhook URL per send_alert call)."""

    __tablename__ = "webhook_delivery_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    alert_key: Mapped[str] = mapped_column(String(200), nullable=False, comment="去重 key")
    event_type: Mapped[str] = mapped_column(String(50), nullable=False, default="source_failure")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False, default="warning")
    webhook_url_preview: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="URL 前 80 字符 + ...（脱敏）"
    )
    status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Integer, nullable=False, default=0, comment="0/1")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_preview: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="响应正文前 500 字符"
    )
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    __table_args__ = (
        Index("ix_webhook_logs_created", "created_at"),
        Index("ix_webhook_logs_event_type", "event_type", "created_at"),
        Index("ix_webhook_logs_alert_key", "alert_key"),
    )

    def __repr__(self) -> str:
        return f"<WebhookDeliveryLog {self.event_type} {'OK' if self.success else 'FAIL'}>"
