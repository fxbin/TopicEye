from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator


class IntegrationStatusResponse(BaseModel):
    provider: str
    configured: bool
    api_key_hint: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    sync_endpoint_configured: bool = False
    install_command: str | None = None
    docs_url: str | None = None
    last_sync_at: datetime | None = None
    last_sync_status: str | None = None
    last_sync_error: str | None = None


class IntegrationUpdateRequest(BaseModel):
    api_key: str = Field(min_length=8, max_length=4096)
    config: dict[str, Any] = Field(default_factory=dict)

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str) -> str:
        api_key = value.strip()
        if len(api_key) < 8:
            raise ValueError("API Key 至少需要 8 个非空字符")
        return api_key


class WeReadSyncResponse(BaseModel):
    fetched: int
    new: int
    duplicates: int
    updated: int = 0
    message: str
    source_name: str


# ── WeRead 搜索 ──


class WeReadSearchBook(BaseModel):
    """搜索结果中的单本书。"""
    bookId: str
    title: str = ""
    author: str = ""
    translator: str = ""
    cover: str = ""
    intro: str = ""
    deepLink: str = ""
    category: str = ""
    publisher: str = ""
    price: float | None = None
    newRating: int | None = None
    newRatingCount: int | None = None
    newRatingDetail: dict[str, Any] = Field(default_factory=dict)
    readingCount: int = 0
    scopeLabel: str = ""


class WeReadSearchResponse(BaseModel):
    """搜索响应。"""
    books: list[WeReadSearchBook]
    hasMore: int = 0
    total: int = 0
    keyword: str = ""


class WeReadBookInfo(BaseModel):
    """书籍详情。"""
    bookId: str
    title: str = ""
    author: str = ""
    translator: str = ""
    cover: str = ""
    intro: str = ""
    deepLink: str = ""
    category: str = ""
    publisher: str = ""
    publishTime: str = ""
    isbn: str = ""
    wordCount: int | None = None
    newRating: int | None = None
    newRatingCount: int | None = None
    newRatingDetail: dict[str, Any] = Field(default_factory=dict)
