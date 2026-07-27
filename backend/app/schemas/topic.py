from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TopicAssetResponse(BaseModel):
    id: int
    content_id: int
    topic_title: str | None = None
    topic_type: str | None = None
    target_platforms: Any | None = None
    target_audience: str | None = None
    creator_score: float | None = 0.0
    viral_score: float | None = 0.0
    status: str
    is_favorited: bool = False
    is_used: bool = False
    feedback: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TopicDetailResponse(TopicAssetResponse):
    pass


class TopicListResponse(BaseModel):
    items: list[TopicAssetResponse]
    total: int
    page: int
    page_size: int
