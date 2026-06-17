from datetime import datetime
from typing import Optional, Any
from pydantic import BaseModel


class AiAnalysisResponse(BaseModel):
    id: int
    content_id: int
    quality_score: float | None = 0.0
    hot_score: float | None = 0.0
    freshness_score: float | None = 0.0
    creator_score: float | None = 0.0
    viral_score: float | None = 0.0
    risk_score: float | None = 0.0
    platform_fit: Any | None = None
    recommended_reason: str | None = None
    summary: str | None = None
    key_points: Any | None = None
    audience_emotion: str | None = None
    creator_angles: Any | None = None
    title_suggestions: Any | None = None
    outline_suggestions: Any | None = None
    xiaohongshu_plan: Any | None = None
    short_video_plan: Any | None = None
    risk_notes: Any | None = None
    # Curation fields
    curation_score: float | None = 0.0
    tags: Any | None = None
    recommendation: str | None = None
    info_density: float | None = 0.0
    actionability: float | None = 0.0
    source_weight: float | None = 0.0
    # Model cascade routing metadata
    analysis_mode: str | None = "pro_only"
    prescreen_model: str | None = None
    final_model: str | None = None
    escalated: bool | None = False
    escalation_reason: str | None = None
    prescreen_confidence: float | None = None
    prescreen_score: float | None = None
    # Round-2 enrichment fields
    enrichment_status: str | None = "pending"
    enrichment: Any | None = None
    # Summary provenance (llm_pro | llm_lite | local_fallback)
    summary_source: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
