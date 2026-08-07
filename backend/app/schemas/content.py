from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_serializer

from app.schemas.analysis import AiAnalysisResponse
from app.services.content_summary import clean_content_summary
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

    @field_serializer("summary")
    def serialize_summary(self, value: str | None) -> str | None:
        # Response-level fallback covers records ingested before summary
        # normalisation was introduced without changing raw article bodies.
        return clean_content_summary(value) or None


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


class ArticleReaderBlock(BaseModel):
    """A safe semantic block extracted from publisher content."""

    type: Literal["heading", "paragraph", "quote", "list_item", "code", "image"]
    # 图片 block 只有 src/alt、没有正文，因此 text 允许缺省为空串
    text: str = ""
    level: int | None = None
    src: str | None = None
    alt: str | None = None


class ArticleReaderResponse(BaseModel):
    """A safe, text-only representation of a source article."""

    content_id: int
    canonical_url: str
    title: str
    byline: str | None = None
    published_at: datetime | None = None
    excerpt: str | None = None
    text_content: str
    content_blocks: list[ArticleReaderBlock] = []
    text_content_zh: str | None = None
    content_blocks_zh: list[ArticleReaderBlock] | None = None
    reading_minutes: int
    extraction_method: str
    fetched_at: datetime
    expires_at: datetime
    cache_status: str


class ContentListResponse(BaseModel):
    items: list[ContentResponse]
    total: int
    page: int
    page_size: int
