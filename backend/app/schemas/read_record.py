from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.read_record import ReadDepth, ReadTargetType


def _normalize_optional_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


class ReadRecordReport(BaseModel):
    """上报一次阅读会话（前端在切换报告/页面隐藏/卸载时上报一次）。"""

    target_type: ReadTargetType
    target_key: str = Field(max_length=64)
    target_id: int | None = None
    duration_ms: int = Field(default=0, ge=0)
    topic_keywords: list[str] | None = None
    category: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_target(self) -> ReadRecordReport:
        if not self.target_key:
            raise ValueError("target_key is required")
        return self

    @field_validator("target_key", "category", mode="before")
    @classmethod
    def normalize_text_fields(cls, value):
        return _normalize_optional_text(value)


class ReadRecordResponse(BaseModel):
    id: int
    user_id: int
    target_type: str
    target_key: str
    target_id: int | None = None
    read_count: int
    accumulated_ms: int
    max_progress: int
    depth: str
    topic_keywords: Any | None = None
    category: str | None = None
    first_read_at: datetime
    last_read_at: datetime
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ReadRecordListResponse(BaseModel):
    items: list[ReadRecordResponse]
    total: int
    page: int
    page_size: int


__all__ = [
    "ReadRecordReport",
    "ReadRecordResponse",
    "ReadRecordListResponse",
    "ReadDepth",
    "ReadTargetType",
]
