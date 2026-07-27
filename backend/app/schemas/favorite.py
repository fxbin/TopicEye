from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.favorite import FavoriteStatus, FavoriteTargetType


def normalize_optional_text(value):
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


class FavoriteCreate(BaseModel):
    target_type: FavoriteTargetType
    target_id: int | None = None
    target_key: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=500)
    url: str | None = Field(default=None, max_length=1024)
    cover_url: str | None = Field(default=None, max_length=1024)
    source_name: str | None = Field(default=None, max_length=255)
    collection_id: int | None = None
    tags: Any | None = None
    note: str | None = None
    status: FavoriteStatus = FavoriteStatus.INBOX
    snapshot: Any | None = None

    @model_validator(mode="after")
    def validate_target_identity(self) -> FavoriteCreate:
        if self.target_id is None and not self.target_key:
            raise ValueError("target_id or target_key is required")
        return self

    @field_validator("target_key", "title", "url", "cover_url", "source_name", "note", mode="before")
    @classmethod
    def normalize_text_fields(cls, value):
        return normalize_optional_text(value)


class FavoriteUpdate(BaseModel):
    collection_id: int | None = None
    tags: Any | None = None
    note: str | None = None
    status: FavoriteStatus | None = None
    snapshot: dict[str, Any] | None = None

    @field_validator("note", mode="before")
    @classmethod
    def normalize_text_fields(cls, value):
        return normalize_optional_text(value)


class FavoriteReorderRequest(BaseModel):
    status: FavoriteStatus
    ordered_ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("ordered_ids")
    @classmethod
    def validate_unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("ordered_ids must not contain duplicates")
        return value


class FavoriteReorderColumn(BaseModel):
    status: FavoriteStatus
    ordered_ids: list[int] = Field(default_factory=list, max_length=500)

    @field_validator("ordered_ids")
    @classmethod
    def validate_unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("ordered_ids must not contain duplicates")
        return value


class FavoriteBoardReorderRequest(BaseModel):
    columns: list[FavoriteReorderColumn] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def validate_unique_columns(self) -> FavoriteBoardReorderRequest:
        statuses = [column.status for column in self.columns]
        if len(statuses) != len(set(statuses)):
            raise ValueError("columns must not contain duplicate statuses")

        ids = [item_id for column in self.columns for item_id in column.ordered_ids]
        if len(ids) != len(set(ids)):
            raise ValueError("ordered_ids must not repeat across columns")
        return self


class FavoriteBulkStatusRequest(BaseModel):
    status: FavoriteStatus
    ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def validate_unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("ids must not contain duplicates")
        return value


class FavoriteBulkDeleteRequest(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=500)

    @field_validator("ids")
    @classmethod
    def validate_unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("ids must not contain duplicates")
        return value


class FavoriteResponse(BaseModel):
    id: int
    user_id: int
    target_type: str
    target_id: int | None = None
    target_key: str
    title: str
    url: str | None = None
    cover_url: str | None = None
    source_name: str | None = None
    collection_id: int | None = None
    tags: Any | None = None
    note: str | None = None
    status: str
    position: int
    snapshot: Any | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    total: int
    page: int
    page_size: int
