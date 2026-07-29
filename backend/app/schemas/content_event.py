"""Public and administrative API contracts for normalized content events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

EventRelation = Literal["duplicate", "corroboration", "update"]


class ContentEventContentResponse(BaseModel):
    """The intentionally small content projection exposed by event APIs."""

    id: int
    title: str
    url: str
    source_name: str | None = None
    source_type: str | None = None
    platform: str | None = None
    published_at: datetime | None = None
    crawled_at: datetime | None = None

    model_config = {"from_attributes": True}


class ContentEventMemberResponse(BaseModel):
    id: int
    content_id: int
    relation_type: EventRelation
    confidence: float = Field(ge=0, le=1)
    title: str
    url: str
    source_name: str | None = None
    source_type: str | None = None
    platform: str | None = None
    published_at: datetime | None = None
    crawled_at: datetime | None = None

    model_config = {"from_attributes": True}


class ContentEventResponse(BaseModel):
    """Visible event data.

    Owner, reviewer and classifier reasoning are deliberately absent from this
    public schema.  The response model therefore strips those service fields
    even if the internal read model contains them.
    """

    id: int
    canonical_id: int
    version: int
    canonical_locked: bool
    canonical: ContentEventContentResponse
    member_count: int = Field(ge=0)
    source_count: int = Field(ge=0)
    has_more: bool
    members: list[ContentEventMemberResponse]

    model_config = {"from_attributes": True}


class ContentEventLookupResponse(BaseModel):
    content_id: int
    event: ContentEventResponse | None


class ContentEventNormalizeRequest(BaseModel):
    hours: int = Field(default=24, ge=1, le=720)
    mode: Literal["shadow", "write"] = "shadow"
    scope: Literal["public", "user"] = "public"
    owner_user_id: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_scope_owner(self) -> ContentEventNormalizeRequest:
        if self.scope == "public" and self.owner_user_id is not None:
            raise ValueError("owner_user_id must be omitted for public scope")
        if self.scope == "user" and self.owner_user_id is None:
            raise ValueError("owner_user_id is required for user scope")
        return self


class ContentEventNormalizeResponse(BaseModel):
    accepted: bool = True
    idempotency_key: str
    mode: Literal["shadow", "write"]
    scope: Literal["public", "user"]
    owner_user_id: int | None = None
    result: dict[str, Any] = Field(default_factory=dict)


class ContentEventReviewItemResponse(BaseModel):
    """Administrative review projection; internal reasoning is admin-only."""

    id: int
    event_id: int
    event_version: int
    content_id: int
    title: str
    source_name: str | None = None
    source_type: str | None = None
    relation_type: EventRelation
    confidence: float = Field(ge=0, le=1)
    match_method: str | None = None
    detector_version: str | None = None
    reason: str | None = None
    review_status: Literal["pending", "auto", "confirmed", "rejected"]
    matched_at: datetime
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ContentEventReviewListResponse(BaseModel):
    items: list[ContentEventReviewItemResponse]
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)


class ContentEventReviewRequest(BaseModel):
    decision: Literal["accept", "reject"]
    relation_type: EventRelation | None = None
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_accept_relation(self) -> ContentEventReviewRequest:
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        if self.decision == "accept" and self.relation_type is None:
            raise ValueError("relation_type is required when decision is accept")
        return self


class ContentEventCanonicalRequest(BaseModel):
    canonical_content_id: int = Field(ge=1)
    former_canonical_relation_type: EventRelation
    reason: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_reason(self) -> ContentEventCanonicalRequest:
        if not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class ContentEventUnlockCanonicalRequest(BaseModel):
    expected_version: int = Field(ge=1)
    reason: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_reason(self) -> ContentEventUnlockCanonicalRequest:
        if self.reason is not None and not self.reason.strip():
            raise ValueError("reason must not be blank")
        return self


class ContentEventMutationResponse(BaseModel):
    event_id: int
    version: int
    canonical_content_id: int
    canonical_locked: bool
