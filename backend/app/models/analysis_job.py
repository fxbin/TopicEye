from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime, Index, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AnalysisJobRecord(Base):
    __tablename__ = "analysis_jobs"

    job_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    content_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    skipped_inflight_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    analyzed_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    failed_ids: Mapped[list[int]] = mapped_column(JSON, nullable=False, default=list)
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    __table_args__ = (Index("ix_analysis_jobs_status_queued", "status", "queued_at"),)
