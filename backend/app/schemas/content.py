from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field, field_serializer

from app.schemas.analysis import AiAnalysisResponse
from app.services.zhihu_url import normalize_zhihu_url


class ContentResponse(BaseModel):
    id: int
    title: str
    url: str
    source_id: int | None = None
    source_name: str | None = None
    source_type: str | None = None
    platform: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    crawled_at: datetime
    content_hash: str | None = None
    summary: str | None = None
    raw_content: str | None = None
    cover_url: str | None = None
    category: str | None = None
    tags: Any | None = None
    language: str | None = None
    status: str
    is_favorited: bool = False
    created_at: datetime
    updated_at: datetime
    analysis: AiAnalysisResponse | None = None

    model_config = {"from_attributes": True}

    @field_serializer("url")
    def serialize_url(self, value: str) -> str:
        return normalize_zhihu_url(value)


class ContentMetricsResponse(BaseModel):
    id: int
    content_id: int
    views: int | None = 0
    likes: int | None = 0
    comments: int | None = 0
    shares: int | None = 0
    favorites: int | None = 0
    followers_count: int | None = 0
    engagement_rate: float | None = 0.0
    explosion_ratio: float | None = 0.0
    snapshot_at: datetime

    model_config = {"from_attributes": True}


class ContentDetailResponse(ContentResponse):
    metrics: list[ContentMetricsResponse] = []


class ContentListResponse(BaseModel):
    items: list[ContentResponse]
    total: int
    page: int
    page_size: int
