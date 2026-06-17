"""
Monthly Digest schema — request/response models.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class MonthlyDigestResponse(BaseModel):
    id: int
    month_key: str
    month_label: str
    month_start: str
    month_end: str
    overview: Optional[str] = None
    takeaway: Optional[str] = None
    keywords: Optional[Any] = None
    trends: Optional[Any] = None
    top_picks: Optional[Any] = None
    category_summary: Optional[Any] = None
    platform_tips: Optional[Any] = None
    topic_clusters: Optional[Any] = None
    action_items: Optional[Any] = None
    content_count: int = 0
    analyzed_count: int = 0
    source_count: int = 0
    category_count: int = 0
    status: str = "PENDING"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = {"from_attributes": True}


class MonthlyDigestListResponse(BaseModel):
    items: list[MonthlyDigestResponse]
    total: int


class MonthlyDigestMonthSummary(BaseModel):
    month_key: str
    month_label: str
    takeaway: Optional[str] = None
    status: str = "PENDING"


class MonthlyDigestMonthsResponse(BaseModel):
    months: list[MonthlyDigestMonthSummary]
