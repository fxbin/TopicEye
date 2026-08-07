"""Public contracts for trend snapshot evidence drill-through."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

TrendProvenanceStatus = Literal["complete", "sample_only", "partial", "unavailable"]


class TrendEvidenceMarkResponse(BaseModel):
    cross_source_level: str
    platform_count: int = Field(ge=0)
    platforms: list[str] = Field(default_factory=list)
    evidence_count: int = Field(ge=0)
    independent_publisher_count: int = Field(ge=0)
    has_primary_source: bool
    has_official_source: bool


class TrendEvidenceItemResponse(BaseModel):
    content_id: int | None = None
    title: str
    url: str
    source_id: int | None = None
    source_name: str | None = None
    source_type: str | None = None
    platform: str | None = None
    published_at: datetime | None = None
    crawled_at: datetime | None = None
    time_basis: Literal["published_at", "crawled_at", "created_at"]
    score: float | None = None
    selected: bool
    evidence_mark: TrendEvidenceMarkResponse | None = None


class TrendEvidenceScopeResponse(BaseModel):
    kind: Literal["topic", "keyword"]
    key: str
    label: str
    start_date: date
    end_date: date


class TrendEvidenceSummaryResponse(BaseModel):
    content_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    selected_count: int = Field(ge=0)
    evidenced_count: int = Field(ge=0)
    provenance_status: TrendProvenanceStatus


class TrendEvidenceCalculationResponse(BaseModel):
    version: str
    generated_at: datetime | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    event_members_excluded: bool = True


class TrendEvidenceDailyCountResponse(BaseModel):
    date: date
    count: int = Field(ge=0)
    provenance_status: TrendProvenanceStatus


class TrendEvidenceResponse(BaseModel):
    scope: TrendEvidenceScopeResponse
    summary: TrendEvidenceSummaryResponse
    calculation: TrendEvidenceCalculationResponse
    daily_counts: list[TrendEvidenceDailyCountResponse]
    items: list[TrendEvidenceItemResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)
    message: str | None = None
