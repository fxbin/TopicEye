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


# ── WeRead 阅读统计 / 热门划线 / 完整书架 ──


class WeReadBookmarkItem(BaseModel):
    """热门划线条目。"""
    chapter_name: str = ""
    text: str = ""
    content_style: int = 0
    create_time: int = 0


class WeReadBestBookmarksResponse(BaseModel):
    """热门划线响应。"""
    book_id: str
    bookmarks: list[WeReadBookmarkItem] = Field(default_factory=list)
    total: int = 0


class WeReadShelfBook(BaseModel):
    """书架中的单本书。"""
    book_id: str
    title: str = ""
    author: str = ""
    cover: str = ""
    category: str = ""
    deep_link: str = ""
    reading_progress: int = 0
    note_count: int = 0
    review_count: int = 0
    book_type: int = 0
    sort: int = 0


class WeReadShelfSyncResponse(BaseModel):
    """完整书架同步响应。"""
    books: list[WeReadShelfBook] = Field(default_factory=list)
    total: int = 0
    has_notes: int = 0
    no_notes: int = 0
    audiobook_count: int = 0


class WeReadReadDataResponse(BaseModel):
    """阅读统计数据响应。"""
    read_type: str = "all"
    total_read_time: int = 0
    total_read_days: int = 0
    total_read_book_count: int = 0
    total_note_count: int = 0
    total_mark_count: int = 0
    ranking_list: list[Any] = Field(default_factory=list)
    preference: dict[str, Any] = Field(default_factory=dict)
