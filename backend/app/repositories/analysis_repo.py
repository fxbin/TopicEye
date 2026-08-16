"""
Repository for AiAnalysis model operations.
"""

from __future__ import annotations

from sqlalchemy import func, or_, select, update

from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.models.source import Source
from app.repositories.analysis_queries import latest_analysis_id_for_content_id
from app.repositories.base import BaseRepository
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import ScoringInput, score_items


class AnalysisRepository(BaseRepository[AiAnalysis]):
    """AiAnalysis table CRUD + content-based lookups."""

    model = AiAnalysis

    async def get_by_content_id(self, content_id: int) -> AiAnalysis | None:
        """Fetch the latest analysis record for a given content item."""
        stmt = (
            select(AiAnalysis)
            .where(AiAnalysis.content_id == content_id)
            .order_by(AiAnalysis.created_at.desc(), AiAnalysis.id.desc())
            .limit(1)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_enrichment_ids(self, min_score: float, limit: int) -> list[int]:
        """Return unified-scored high-value content IDs that still need enrichment."""
        latest_id = latest_analysis_id_for_content_id(AiAnalysis.content_id)
        stmt = (
            select(AiAnalysis, ContentItem, Source.weight.label("source_weight_db"))
            .select_from(AiAnalysis)
            .join(ContentItem, ContentItem.id == AiAnalysis.content_id)
            .outerjoin(Source, Source.id == ContentItem.source_id)
            .where(
                AiAnalysis.id == latest_id,
                or_(
                    AiAnalysis.enrichment_status.is_(None),
                    AiAnalysis.enrichment_status.in_(("pending", "error")),
                ),
            )
            .order_by(AiAnalysis.curation_score.desc(), AiAnalysis.created_at.desc())
            .limit(max(limit * 5, limit))
        )
        result = await self.db.execute(stmt)
        rows = result.all()
        feedback_scores = await get_feedback_scores(
            self.db,
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

    async def claim_pending_enrichment_ids(self, min_score: float, limit: int) -> list[int]:
        """Claim unified-scored enrichment candidates so concurrent batches do not duplicate work."""

        async def _claim() -> list[int]:
            candidate_ids = await self.get_pending_enrichment_ids(min_score, limit)
            if not candidate_ids:
                return []

            latest_id = latest_analysis_id_for_content_id(AiAnalysis.content_id)
            lock_stmt = (
                select(AiAnalysis.id, AiAnalysis.content_id)
                .where(AiAnalysis.id == latest_id)
                .where(AiAnalysis.content_id.in_(candidate_ids))
                .where(
                    or_(
                        AiAnalysis.enrichment_status.is_(None),
                        AiAnalysis.enrichment_status.in_(("pending", "error")),
                    )
                )
            )
            lock_stmt = lock_stmt.with_for_update(skip_locked=True)

            result = await self.db.execute(lock_stmt)
            locked_rows = result.all()
            if not locked_rows:
                return []

            analysis_ids_by_content = {int(content_id): int(analysis_id) for analysis_id, content_id in locked_rows}
            ordered_content_ids = [
                int(content_id) for content_id in candidate_ids if int(content_id) in analysis_ids_by_content
            ][:limit]
            analysis_ids = [analysis_ids_by_content[content_id] for content_id in ordered_content_ids]
            if not analysis_ids:
                return []

            update_result = await self.db.execute(
                update(AiAnalysis)
                .where(AiAnalysis.id.in_(analysis_ids))
                .where(
                    or_(
                        AiAnalysis.enrichment_status.is_(None),
                        AiAnalysis.enrichment_status.in_(("pending", "error")),
                    )
                )
                .values(enrichment_status="processing")
            )
            await self.db.flush()
            if update_result.rowcount == len(analysis_ids):
                return ordered_content_ids

            refreshed = await self.db.execute(
                select(AiAnalysis.content_id)
                .where(AiAnalysis.id.in_(analysis_ids))
                .where(AiAnalysis.enrichment_status == "processing")
            )
            refreshed_content_ids = {int(row[0]) for row in refreshed.all()}
            return [content_id for content_id in ordered_content_ids if content_id in refreshed_content_ids]

        return await _claim()

    async def claim_enrichment_for_content(self, content_id: int) -> AiAnalysis | None:
        """Claim the latest analysis for one content item before running enrichment."""

        async def _claim() -> AiAnalysis | None:
            latest_id = latest_analysis_id_for_content_id(AiAnalysis.content_id)
            lock_stmt = (
                select(AiAnalysis)
                .where(AiAnalysis.id == latest_id)
                .where(AiAnalysis.content_id == content_id)
                .where(
                    or_(
                        AiAnalysis.enrichment_status.is_(None),
                        AiAnalysis.enrichment_status.in_(("pending", "error")),
                    )
                )
            )
            lock_stmt = lock_stmt.with_for_update(skip_locked=True)

            result = await self.db.execute(lock_stmt)
            analysis = result.scalar_one_or_none()
            if analysis is None:
                return None

            update_result = await self.db.execute(
                update(AiAnalysis)
                .where(AiAnalysis.id == analysis.id)
                .where(
                    or_(
                        AiAnalysis.enrichment_status.is_(None),
                        AiAnalysis.enrichment_status.in_(("pending", "error")),
                    )
                )
                .values(enrichment_status="processing")
            )
            await self.db.flush()
            if update_result.rowcount != 1:
                return None

            analysis.enrichment_status = "processing"
            return analysis

        return await _claim()

    async def list_with_score_filter(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        min_creator_score: float | None = None,
        min_viral_score: float | None = None,
    ):
        """List analyses with optional score thresholds."""

        filters = {}
        if min_creator_score is not None:
            filters["min_creator_score"] = min_creator_score
        if min_viral_score is not None:
            filters["min_viral_score"] = min_viral_score

        latest_id = latest_analysis_id_for_content_id(AiAnalysis.content_id)
        stmt = select(AiAnalysis).where(AiAnalysis.id == latest_id)
        count_stmt = select(func.count()).select_from(AiAnalysis).where(AiAnalysis.id == latest_id)

        if min_creator_score is not None:
            stmt = stmt.where(AiAnalysis.creator_score >= min_creator_score)
            count_stmt = count_stmt.where(AiAnalysis.creator_score >= min_creator_score)
        if min_viral_score is not None:
            stmt = stmt.where(AiAnalysis.viral_score >= min_viral_score)
            count_stmt = count_stmt.where(AiAnalysis.viral_score >= min_viral_score)

        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        stmt = stmt.order_by(AiAnalysis.created_at.desc())
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        result = await self.db.execute(stmt)
        items = result.scalars().all()
        return items, total
