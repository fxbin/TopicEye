"""Agent-native scoring API.

Exposes the topic-curation scoring engine as a stable HTTP API so external
agents (Claude Code, Codex, n8n, custom scripts) can call it as their
ranking layer. Two endpoints:

  POST /api/v1/scoring/score  — full curation pipeline (6-dim weighted)
  POST /api/v1/scoring/lfv    — low-follower-viral detection

Both accept the same request shape and return the same response shape.
Auth uses Depends(get_current_user) which accepts both browser session
tokens and personal API tokens (create one at /me/api-tokens).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.models.user import User
from app.schemas.scoring import (
    ScoreBreakdownResponse,
    ScoreResultItem,
    ScoringRequest,
    ScoringResponse,
)
from app.services.scoring_engine import ScoringInput, score_items, score_low_follower_viral


router = APIRouter(prefix="/scoring", tags=["scoring"], dependencies=[Depends(get_current_user)])


def _parse_dt(value: Any) -> datetime | None:
    """Parse ISO 8601 string / datetime / None into datetime | None."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _request_to_scoring_input(item) -> ScoringInput:
    """Adapt a Pydantic ScoringRequestItem → engine ScoringInput (POPROW).

    Mirrors digest_context._row_to_scoring_input but operates on the typed
    request schema instead of a raw dict.
    """
    return ScoringInput(
        content_id=item.content_id,
        title=item.title or "",
        category=item.category,
        source_id=item.source_id,
        source_name=item.source_name,
        published_at=_parse_dt(item.published_at),
        crawled_at=_parse_dt(item.crawled_at),
        curation_score=item.curation_score or 0,
        info_density=item.info_density if item.info_density is not None else 50,
        actionability=item.actionability if item.actionability is not None else 50,
        source_weight=item.source_weight if item.source_weight is not None else 50,
        creator_score=item.creator_score or 0,
        viral_score=item.viral_score or 0,
        freshness_score=item.freshness_score if item.freshness_score is not None else 50,
        quality_score=item.quality_score or 0,
        hot_score=item.hot_score or 0,
        risk_score=item.risk_score or 0,
        source_weight_db=item.source_weight_db or 3,
        feedback_score=item.feedback_score or 0,
    )


def _build_response(scored) -> ScoringResponse:
    """Convert engine output [(ScoreBreakdown, ScoringInput)] → ScoringResponse."""
    results = [
        ScoreResultItem(
            content_id=inp.content_id,
            score=ScoreBreakdownResponse(
                content_id=inp.content_id,
                base_score=bd.base_score,
                source_bonus=bd.source_bonus,
                quality_factor=bd.quality_factor,
                risk_factor=bd.risk_factor,
                time_decay=bd.time_decay,
                diversity_factor=bd.diversity_factor,
                final_score=bd.final_score,
                dimension_scores=bd.dimension_scores or {},
                selected=bd.selected,
                threshold_used=bd.threshold_used,
            ),
        )
        for bd, inp in scored
    ]
    return ScoringResponse(results=results, count=len(results))


@router.post(
    "/score",
    response_model=ScoringResponse,
    summary="Score a batch of content items",
    description=(
        "Run items through the full curation pipeline: 6-dimension weighted base score "
        "+ source bonus + quality gate + risk filter + time decay + diversity penalty. "
        "Returns the complete ScoreBreakdown so callers can explain *why* each item scored "
        "the way it did. Results are sorted by final_score descending. "
        "Items with risk_score > 82 are hard-excluded."
    ),
)
async def score_content(req: ScoringRequest, current_user: User = Depends(get_current_user)):
    inputs = [_request_to_scoring_input(item) for item in req.items]
    scored = score_items(inputs)
    return _build_response(scored)


@router.post(
    "/lfv",
    response_model=ScoringResponse,
    summary="Low-follower-viral detection",
    description=(
        "Identify breakout candidates from low-follower sources. Uses a different scoring "
        "formula than /score: lfv = (viral*0.45 + creator*0.30 + quality*0.25) * obscure_factor "
        "* freshness_boost, where obscure_factor rewards low source authority. "
        "Use this to find content that's heating up before the source itself becomes popular."
    ),
)
async def score_lfv(req: ScoringRequest, current_user: User = Depends(get_current_user)):
    inputs = [_request_to_scoring_input(item) for item in req.items]
    scored = score_low_follower_viral(inputs)
    return _build_response(scored)
