"""
Daily Report schema — request/response models.
"""

import json
from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field, field_serializer

from app.services.zhihu_url import normalize_zhihu_url


def _parse_json_value(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _normalize_top_pick_urls(value: Any) -> Any:
    parsed = _parse_json_value(value)
    if isinstance(parsed, list):
        for pick in parsed:
            if isinstance(pick, dict) and "source_url" in pick:
                pick["source_url"] = normalize_zhihu_url(pick.get("source_url"))
    return parsed


class DailyReportResponse(BaseModel):
    id: int
    owner_user_id: Optional[int] = None
    report_date: str
    weekday: str
    edition: str = "snapshot"
    generated_at: Optional[datetime] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    cutoff_at: Optional[datetime] = None
    source_scope: str = "curated"
    source_item_ids: Optional[Any] = None
    overview: Optional[str] = None
    takeaway: Optional[str] = None
    keywords: Optional[Any] = None  # parsed JSON array
    trends: Optional[Any] = None  # parsed JSON array
    top_picks: Optional[Any] = None  # parsed JSON array
    platform_tips: Optional[Any] = None  # parsed JSON object
    topic_count: int = 0
    content_count: int = 0
    analyzed_count: int = 0
    status: str = "PENDING"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}

    @field_serializer("keywords", "trends", "platform_tips", "source_item_ids")
    def serialize_json_fields(self, value: Any) -> Any:
        return _parse_json_value(value)

    @field_serializer("top_picks")
    def serialize_top_picks(self, value: Any) -> Any:
        return _normalize_top_pick_urls(value)


class DailyReportListResponse(BaseModel):
    items: list[DailyReportResponse]
    total: int


class DailyReportDateSummary(BaseModel):
    """Lightweight summary for the date sidebar."""

    report_date: str
    weekday: str
    takeaway: Optional[str] = None
    status: str = "PENDING"
    edition: str = "snapshot"
    generated_at: Optional[datetime] = None
    cutoff_at: Optional[datetime] = None


class DailyReportDatesResponse(BaseModel):
    """Response for the dates-list endpoint."""

    dates: list[DailyReportDateSummary]


class DailyReportCalendarDay(BaseModel):
    """One day in the report recovery calendar."""

    report_date: str
    weekday: str
    status: str = "MISSING"
    edition: Optional[str] = None
    generated_at: Optional[datetime] = None
    cutoff_at: Optional[datetime] = None
    takeaway: Optional[str] = None
    content_count: int = 0
    analyzed_count: int = 0
    topic_count: int = 0
    has_report: bool = False
    can_generate: bool = True
    is_today: bool = False


class DailyReportCalendarResponse(BaseModel):
    """Response for the daily-report date map."""

    days: list[DailyReportCalendarDay]
    total_days: int
    done_count: int
    error_count: int
    missing_count: int
    generating_count: int
