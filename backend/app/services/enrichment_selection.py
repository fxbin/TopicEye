"""Select and claim enrichment candidates using the shared scoring engine.

Database reads and row claims remain in AnalysisRepository. The caller owns
commit/rollback, so claiming stays atomic with its existing transaction.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.analysis_repo import AnalysisRepository
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import ScoringInput, score_items


async def get_pending_enrichment_ids(db: AsyncSession, min_score: float, limit: int) -> list[int]:
    rows = await AnalysisRepository(db).list_pending_enrichment_candidates(max(limit * 5, limit))
    feedback_scores = await get_feedback_scores(
        db,
        [int(analysis.content_id) for analysis, _content, _source_weight in rows],
    )
    candidate_ids: set[int] = set()
    scoring_inputs: list[ScoringInput] = []
    for analysis, content, source_weight_db in rows:
        candidate_ids.add(int(analysis.content_id))
        scoring_inputs.append(
            ScoringInput(
                content_id=int(analysis.content_id),
                title=content.title,
                category=content.category,
                summary_source=analysis.summary_source,
                source_id=content.source_id,
                source_name=content.source_name,
                published_at=content.published_at,
                crawled_at=content.crawled_at,
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
                source_weight_db=source_weight_db or 3,
                feedback_score=feedback_scores.get(int(analysis.content_id), 0),
            )
        )

    return [
        int(item.content_id)
        for breakdown, item in score_items(scoring_inputs)
        if breakdown.selected and breakdown.final_score >= min_score and item.content_id in candidate_ids
    ][:limit]


async def claim_pending_enrichment_ids(db: AsyncSession, min_score: float, limit: int) -> list[int]:
    candidate_ids = await get_pending_enrichment_ids(db, min_score, limit)
    return await AnalysisRepository(db).claim_enrichment_candidates(candidate_ids)
