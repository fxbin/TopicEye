from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.product_feedback import (
    IssueFeedbackSeverity,
    IssueFeedbackStatus,
    ProductUpdateKind,
    ProductUpdateStatus,
)


def _clean_text(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class IssueFeedbackCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    area: str = Field(default="general", min_length=1, max_length=80)
    severity: IssueFeedbackSeverity = IssueFeedbackSeverity.medium

    @field_validator("title", "description", "area", mode="before")
    @classmethod
    def clean_required_text(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip()


class IssueFeedbackUpdate(BaseModel):
    status: Optional[IssueFeedbackStatus] = None
    severity: Optional[IssueFeedbackSeverity] = None
    area: Optional[str] = Field(default=None, min_length=1, max_length=80)
    resolution_note: Optional[str] = Field(default=None, max_length=5000)

    @field_validator("area", "resolution_note", mode="before")
    @classmethod
    def clean_optional_text(cls, value: Optional[str]) -> Optional[str]:
        return _clean_text(value)


class IssueFeedbackResponse(BaseModel):
    id: int
    user_id: Optional[int] = None
    title: str
    description: str
    area: str
    severity: IssueFeedbackSeverity
    status: IssueFeedbackStatus
    resolution_note: Optional[str] = None
    fixed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    reporter_email: Optional[str] = None
    reporter_name: Optional[str] = None

    model_config = {"from_attributes": True}


class IssueFeedbackListResponse(BaseModel):
    items: list[IssueFeedbackResponse]
    total: int
    open_count: int
    fixed_count: int


# ── Product updates: 1 version = 1 record, items[] 装多条更新 ────────────────


class ProductUpdateEntry(BaseModel):
    """版本里的一项更新。kind 仅决定展示图标 (release/improvement/fix/roadmap)。"""

    title: str = Field(min_length=2, max_length=200)
    description: str = Field(min_length=5, max_length=5000)
    kind: ProductUpdateKind = ProductUpdateKind.improvement

    @field_validator("title", "description", mode="before")
    @classmethod
    def clean_text(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        return value.strip()


class ProductUpdateCreate(BaseModel):
    """创建一个版本记录。items 必填，至少 1 条。"""

    version: str = Field(min_length=1, max_length=50)
    status: ProductUpdateStatus = ProductUpdateStatus.planned
    target_date: Optional[date] = None
    shipped_at: Optional[datetime] = None
    items: list[ProductUpdateEntry] = Field(min_length=1)

    @field_validator("version", mode="before")
    @classmethod
    def clean_version(cls, value: str) -> str:
        return _clean_text(value)


class ProductUpdatePatch(BaseModel):
    version: Optional[str] = Field(default=None, min_length=1, max_length=50)
    status: Optional[ProductUpdateStatus] = None
    target_date: Optional[date] = None
    shipped_at: Optional[datetime] = None
    items: Optional[list[ProductUpdateEntry]] = Field(default=None, min_length=1)

    @field_validator("version", mode="before")
    @classmethod
    def clean_version(cls, value: Optional[str]) -> Optional[str]:
        return _clean_text(value)


class ProductUpdateResponse(BaseModel):
    """1 个版本对应 1 条记录; 该版本的多项更新挂在 items[] 上."""

    id: int
    version: str
    status: ProductUpdateStatus
    target_date: Optional[date] = None
    shipped_at: Optional[datetime] = None
    items: list[ProductUpdateEntry]
    created_by_id: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProductUpdateListResponse(BaseModel):
    items: list[ProductUpdateResponse]
    total: int
