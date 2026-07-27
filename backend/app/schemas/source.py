from __future__ import annotations

import json
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, Field, field_validator

from app.models.source import SourceStatus, SourceType

API_SOURCE_ALLOWED_METHODS = {"GET", "POST"}


def normalize_source_url_value(value: str) -> str:
    url = value.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme in {"http", "https"} and parts.netloc:
        netloc = parts.netloc.lower()
        return urlunsplit((scheme, netloc, parts.path, parts.query, parts.fragment))
    raise ValueError("信源 URL 必须以 http:// 或 https:// 开头")


def normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def normalize_api_source_config_value(value: str | None) -> str | None:
    """Validate and normalize JSON stored in Source.keyword for API sources."""
    text = normalize_optional_text(value)
    if text is None:
        return None
    try:
        config = json.loads(text)
    except json.JSONDecodeError:
        raise ValueError("API 信源配置必须是合法 JSON 对象") from None
    if not isinstance(config, dict):
        raise ValueError("API 信源配置必须是合法 JSON 对象") from None

    method = config.get("method")
    if method is not None:
        if not isinstance(method, str) or method.strip().upper() not in API_SOURCE_ALLOWED_METHODS:
            raise ValueError("API 信源 method 仅支持 GET 或 POST") from None
        config["method"] = method.strip().upper()

    for key in ("headers", "params", "body", "fields"):
        if key in config and config[key] is not None and not isinstance(config[key], dict):
            raise ValueError(f"API 信源 {key} 必须是 JSON 对象")

    items_path = config.get("items_path")
    if items_path is not None:
        if not isinstance(items_path, str) or not items_path.strip():
            raise ValueError("API 信源 items_path 必须是非空字符串")
        config["items_path"] = items_path.strip()

    fields = config.get("fields")
    if isinstance(fields, dict):
        for field_name, path in fields.items():
            if not isinstance(field_name, str) or not field_name.strip():
                raise ValueError("API 信源 fields 的字段名必须是非空字符串")
            if not isinstance(path, str) or not path.strip():
                raise ValueError("API 信源 fields 的路径必须是非空字符串")

    timeout = config.get("timeout")
    if timeout is not None:
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            raise ValueError("API 信源 timeout 必须是 1 到 120 秒之间的数字") from None
        if timeout_value < 1 or timeout_value > 120:
            raise ValueError("API 信源 timeout 必须是 1 到 120 秒之间的数字") from None
        config["timeout"] = timeout_value

    return json.dumps(config, ensure_ascii=False, separators=(",", ":"))


class SourceCreate(BaseModel):
    name: str = Field(..., max_length=255)
    source_type: SourceType = SourceType.RSS
    url: str = Field(..., max_length=1024)
    keyword: str | None = None
    platform: str | None = None
    category: str | None = None
    weight: int = Field(default=3, ge=1, le=5)
    sort_order: int | None = Field(default=None, ge=0)
    fetch_interval_minutes: int = Field(default=60, ge=5, le=1440)
    enabled: bool = True

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("信源名称不能为空")
        return name

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str) -> str:
        return normalize_source_url_value(value)

    @field_validator("keyword", "platform", "category")
    @classmethod
    def normalize_optional_text_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class SourceUpdate(BaseModel):
    name: str | None = None
    source_type: SourceType | None = None
    url: str | None = None
    keyword: str | None = None
    platform: str | None = None
    category: str | None = None
    weight: int | None = Field(default=None, ge=1, le=5)
    sort_order: int | None = Field(default=None, ge=0)
    fetch_interval_minutes: int | None = Field(default=None, ge=5, le=1440)
    status: SourceStatus | None = None
    sync_error: str | None = None
    enabled: bool | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        name = value.strip()
        if not name:
            raise ValueError("信源名称不能为空")
        return name

    @field_validator("url")
    @classmethod
    def normalize_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return normalize_source_url_value(value)

    @field_validator("keyword", "platform", "category", "sync_error")
    @classmethod
    def normalize_optional_text_fields(cls, value: str | None) -> str | None:
        return normalize_optional_text(value)


class SourceResponse(BaseModel):
    id: int
    owner_user_id: int | None = None
    scope: str = "system"
    name: str
    source_type: str
    url: str
    keyword: str | None = None
    platform: str | None = None
    category: str | None = None
    weight: int
    sort_order: int
    fetch_interval_minutes: int
    status: str
    last_sync_at: datetime | None = None
    sync_error: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    items: list[SourceResponse]
    total: int
    page: int
    page_size: int
    # 私有信源配额（仅 GET /sources/me 填充；公共列表留空）
    private_sources_used: int | None = None
    private_sources_quota: int | None = None


class SourceReorderRequest(BaseModel):
    ordered_ids: list[int] = Field(..., min_length=1)

    @field_validator("ordered_ids")
    @classmethod
    def validate_unique_ids(cls, value):
        if len(value) != len(set(value)):
            raise ValueError("ordered_ids must not contain duplicates")
        return value


class SyncResultResponse(BaseModel):
    """Result of syncing a single source."""

    fetched: int
    new: int
    duplicates: int
    source_info: SourceResponse

    model_config = {"from_attributes": True}
