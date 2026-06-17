from __future__ import annotations
from typing import Optional
from datetime import datetime
from pydantic import BaseModel


class FeedbackCreate(BaseModel):
    content_id: int
    feedback_type: str
    comment: str | None = None


class FeedbackResponse(BaseModel):
    id: int
    user_id: int
    content_id: int
    feedback_type: str
    score_delta: float
    comment: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


class FeedbackStatsResponse(BaseModel):
    total: int
    by_type: dict[str, int]
    avg_score_delta: float
