"""Pydantic schemas for the Agent-native scoring API (/scoring/score, /scoring/lfv).

These mirror the lightweight ScoringInput / ScoreBreakdown POPO classes in
app/services/scoring_engine.py so they show up in the OpenAPI docs and can be
consumed by external agents / CLIs / MCP servers.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

# ── Request ──────────────────────────────────────────────────────────


class ScoringRequestItem(BaseModel):
    """A single content item to be scored.

    Only ``content_id`` is required — it lets the caller correlate results.
    All scoring dimensions default to neutral values so a caller with partial
    data still gets a meaningful score. Dimensions are 0-100 unless noted.
    """

    content_id: int = Field(..., description="Caller-side identifier to correlate with the result.")
    title: str = Field("", description="Item title. Used for diversity tie-breaking, not weighted directly.")
    category: Optional[str] = Field(None, description="Category label. Used for diversity mixing.")
    source_id: Optional[int] = Field(None, description="Source identifier. Currently informational.")
    source_name: Optional[str] = Field(None, description="Source name. Used for diversity mixing.")

    # Time fields — accept ISO 8601 string or datetime. None = treat as "now".
    published_at: Optional[datetime | str] = Field(
        None, description="Publication time (ISO 8601). Falls back to crawled_at, then now."
    )
    crawled_at: Optional[datetime | str] = Field(
        None, description="Crawl time (ISO 8601). Falls back to now if published_at is also missing."
    )

    # Analysis dimensions (0-100 typical range)
    curation_score: float = Field(0, ge=0, le=100, description="Composite curation score if already computed.")
    info_density: float = Field(50, ge=0, le=100, description="Information density (weight 0.25).")
    actionability: float = Field(50, ge=0, le=100, description="Actionability for creators (weight 0.20).")
    source_weight: float = Field(50, ge=0, le=100, description="Analysis-layer source authority (weight 0.12).")
    creator_score: float = Field(0, ge=0, le=100, description="Creator value (weight 0.18).")
    viral_score: float = Field(0, ge=0, le=100, description="Viral potential (weight 0.15).")
    freshness_score: float = Field(50, ge=0, le=100, description="Freshness signal (weight 0.10).")
    quality_score: float = Field(0, ge=0, le=100, description="Overall quality. Used in quality gate, not weighted sum.")
    hot_score: float = Field(0, ge=0, le=100, description="Heat score. Used in fallback only.")
    risk_score: float = Field(0, ge=0, le=100, description="Risk score. Items above risk_threshold (82) are hard-excluded.")

    # Source tier from the DB (1-5). Drives the source_bonus adjustment.
    source_weight_db: int = Field(3, ge=1, le=5, description="Source tier 1-5 from the DB. Drives source_bonus.")

    # User feedback signal (e.g. summed like/dislike deltas). 0 = no signal.
    feedback_score: float = Field(0, description="Aggregated user feedback signal. Clamped to [-20, 20] internally.")


class ScoringRequest(BaseModel):
    """Batch scoring request. Max 50 items per call to bound cost."""

    items: list[ScoringRequestItem] = Field(..., min_length=1, max_length=50, description="Items to score (1-50).")


# ── Response ─────────────────────────────────────────────────────────


class ScoreBreakdownResponse(BaseModel):
    """Full breakdown of how a score was computed — the transparency layer.

    Every selected/rejected item returns this so callers can explain *why*
    an item scored the way it did (6 dimensions + 4 factors + threshold).
    """

    content_id: int
    base_score: float = Field(..., description="Weighted 6-dimension sum (before adjustments).")
    source_bonus: float = Field(..., description="Bonus from source_weight_db tier.")
    quality_factor: float = Field(..., description="Quality gate multiplier (0-1, lower = thinner content).")
    risk_factor: float = Field(..., description="Soft risk multiplier (0-1, lower = riskier).")
    time_decay: float = Field(..., description="Time decay multiplier (0-1, lower = older).")
    diversity_factor: float = Field(..., description="Diversity penalty multiplier (0-1, lower = duplicate-heavy).")
    final_score: float = Field(..., description="Final curation score after all adjustments.")
    dimension_scores: dict[str, Any] = Field(
        ..., description="Per-dimension weighted contributions (info_density, actionability, ...)."
    )
    selected: bool = Field(..., description="Whether the item passes the curation threshold.")
    threshold_used: float = Field(..., description="Actual threshold applied (percentile or fixed).")


class ScoreResultItem(BaseModel):
    """One scored item: the caller's content_id + its full breakdown."""

    content_id: int
    score: ScoreBreakdownResponse


class ScoringResponse(BaseModel):
    """Scoring result. Items are sorted by final_score descending."""

    results: list[ScoreResultItem]
    count: int = Field(..., description="Number of items in results (may be < request if risk-filtered).")
