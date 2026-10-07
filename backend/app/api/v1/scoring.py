"""Agent-native scoring API.

Exposes the topic-curation scoring engine as a stable HTTP API so external
agents (Claude Code, Codex, n8n, custom scripts) can call it as their
ranking layer:

  POST /api/v1/scoring/score  — full curation pipeline (6-dim weighted)

Auth uses Depends(get_current_user) which accepts both browser session
tokens and personal API tokens (create one at /me/api-tokens).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.api.v1.auth import get_current_user
from app.models.user import User
from app.schemas.scoring import ScoringRequest, ScoringResponse
from app.services.scoring_engine import build_scoring_response, request_item_to_scoring_input, score_items

router = APIRouter(prefix="/scoring", tags=["scoring"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


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
    inputs = [request_item_to_scoring_input(item) for item in req.items]
    scored = score_items(inputs)
    logger.info("Scoring /score: user_id=%d, items=%d", current_user.id, len(inputs))
    return build_scoring_response(scored)
