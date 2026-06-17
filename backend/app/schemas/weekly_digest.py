"""
Weekly Digest schema — request/response models.
"""

from datetime import datetime
from typing import Optional, Any

from pydantic import BaseModel, Field


class WeeklyDigestResponse(BaseModel):
    id: int
    week_key: str
    week_label: str
    week_start: str
    week_end: str
    overview: Optional[str] = None
    takeaway: Optional[str] = None
    keywords: Optional[Any] = None  # parsed JSON array
    trends: Optional[Any] = None  # parsed JSON array
    top_picks: Optional[Any] = None  # parsed JSON array
    category_summary: Optional[Any] = None  # parsed JSON object
    platform_tips: Optional[Any] = None  # parsed JSON object
    topic_clusters: Optional[Any] = None  # parsed JSON array
    action_items: Optional[Any] = None  # parsed JSON array
    content_count: int = 0
    analyzed_count: int = 0
    source_count: int = 0
    category_count: int = 0
    status: str = "PENDING"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class WeeklyDigestListResponse(BaseModel):
    items: list[WeeklyDigestResponse]
    total: int


class WeeklyDigestWeekSummary(BaseModel):
    """Lightweight summary for the week sidebar."""

    week_key: str
    week_label: str
    takeaway: Optional[str] = None
    status: str = "PENDING"


class WeeklyDigestWeeksResponse(BaseModel):
    """Response for the weeks-list endpoint."""

    weeks: list[WeeklyDigestWeekSummary]
