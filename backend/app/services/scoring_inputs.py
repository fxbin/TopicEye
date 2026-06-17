"""Adapters from ORM content rows to scoring engine inputs."""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.content_serialization import latest_analysis_from_item
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import ScoringInput


async def build_scoring_inputs(
    db: AsyncSession,
    items: list[Any],
) -> tuple[list[ScoringInput], dict[int, Any], dict[int, float]]:
    """Build scoring inputs and lookup maps for content rows with analyses."""
    feedback_scores = await get_feedback_scores(db, [item.id for item in items])
    scoring_inputs: list[ScoringInput] = []
    item_map: dict[int, Any] = {}

    for item in items:
        if latest_analysis_from_item(item) is None:
            continue
        scoring_input = build_scoring_input(item, feedback_scores.get(item.id, 0))
        scoring_inputs.append(scoring_input)
        item_map[item.id] = item

    return scoring_inputs, item_map, feedback_scores


def build_scoring_input(item: Any, feedback_score: float = 0) -> ScoringInput:
    """Convert a content ORM row into a ScoringInput."""
    analysis = latest_analysis_from_item(item)
    if analysis is None:
        raise ValueError("Content item has no loaded analyses")
    source_weight = item.source.weight if item.source else 3
    return ScoringInput(
        content_id=item.id,
        title=item.title,
        category=item.category,
        source_id=item.source_id,
        source_name=item.source_name,
        published_at=item.published_at,
        crawled_at=item.crawled_at,
        curation_score=analysis.curation_score or 0,
        info_density=analysis.info_density or 50,
        actionability=analysis.actionability or 50,
        source_weight=analysis.source_weight or 50,
        creator_score=analysis.creator_score or 0,
        viral_score=analysis.viral_score or 0,
        freshness_score=analysis.freshness_score or 0,
        quality_score=analysis.quality_score or 0,
        hot_score=analysis.hot_score or 0,
        risk_score=analysis.risk_score or 0,
        source_weight_db=source_weight,
        feedback_score=feedback_score,
    )
