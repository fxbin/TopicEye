"""
Monthly Digest schema — request/response models.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class MonthlyDigestResponse(BaseModel):
    id: int
    month_key: str
    month_label: str
    month_start: str
    month_end: str
    overview: str | None = None
    takeaway: str | None = None
    keywords: Any | None = None
    trends: Any | None = None
    top_picks: Any | None = None
    category_summary: Any | None = None
    platform_tips: Any | None = None
    topic_clusters: Any | None = None
    action_items: Any | None = None
    content_count: int = 0
    analyzed_count: int = 0
    source_count: int = 0
    category_count: int = 0
    status: str = "PENDING"
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class MonthlyDigestListResponse(BaseModel):
    items: list[MonthlyDigestResponse]
    total: int


class MonthlyDigestMonthSummary(BaseModel):
    month_key: str
    month_label: str
    takeaway: str | None = None
    status: str = "PENDING"


class MonthlyDigestMonthsResponse(BaseModel):
    months: list[MonthlyDigestMonthSummary]
