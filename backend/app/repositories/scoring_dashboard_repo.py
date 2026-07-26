"""Repository for scoring dashboard aggregated reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis import AiAnalysis
from app.models.favorite import FavoriteItem, FavoriteTargetType
from app.models.feedback import UserFeedback
from app.models.ignored import IgnoredItem
from app.models.user_interest_vector import UserInterestVector


class ScoringDashboardRepository:
    """Aggregate queries for the scoring feedback dashboard."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_dashboard_data(self, cutoff: datetime) -> dict[str, Any]:
        """Return all dashboard data in a single call."""
        # 1. Feedback distribution
        fb_result = await self.db.execute(
            select(
                UserFeedback.feedback_type,
                func.count().label("count"),
            )
            .where(UserFeedback.created_at >= cutoff)
            .group_by(UserFeedback.feedback_type)
        )
        feedback_dist: dict[str, int] = {}
        for row in fb_result.all():
            feedback_dist[row.feedback_type] = row.count
        total_feedback = sum(feedback_dist.values())

        # 2. Favorites count
        fav_result = await self.db.execute(
            select(func.count())
            .select_from(FavoriteItem)
            .where(
                FavoriteItem.target_type == FavoriteTargetType.CONTENT,
                FavoriteItem.created_at >= cutoff,
            )
        )
        favorites_count = int(fav_result.scalar() or 0)

        # 3. Ignores count
        ignore_result = await self.db.execute(
            select(func.count())
            .select_from(IgnoredItem)
            .where(IgnoredItem.created_at >= cutoff)
        )
        ignores_count = int(ignore_result.scalar() or 0)

        # 4. Content analyzed in the period
        content_result = await self.db.execute(
            select(func.count())
            .select_from(AiAnalysis)
            .where(AiAnalysis.created_at >= cutoff)
        )
        analyzed_count = int(content_result.scalar() or 0)

        # 5. Personalization: user interest vector stats
        vector_result = await self.db.execute(
            select(
                UserInterestVector.user_id,
                func.count().label("tag_count"),
                func.sum(func.abs(UserInterestVector.weight)).label("total_weight"),
            )
            .group_by(UserInterestVector.user_id)
        )
        vector_rows = vector_result.all()
        users_with_vectors = len(vector_rows)

        # Top tags by absolute weight across all users
        top_tags_result = await self.db.execute(
            select(
                UserInterestVector.tag,
                func.avg(UserInterestVector.weight).label("avg_weight"),
                func.sum(func.abs(UserInterestVector.weight)).label("total_weight"),
                func.count().label("user_count"),
            )
            .group_by(UserInterestVector.tag)
            .order_by(func.sum(func.abs(UserInterestVector.weight)).desc())
            .limit(20)
        )
        top_tags = [
            {
                "tag": row.tag,
                "avg_weight": round(float(row.avg_weight or 0), 2),
                "total_weight": round(float(row.total_weight or 0), 2),
                "user_count": row.user_count,
            }
            for row in top_tags_result.all()
        ]

        # 6. Daily feedback trend
        daily_result = await self.db.execute(
            select(
                func.date(UserFeedback.created_at).label("date"),
                func.count().label("count"),
            )
            .where(UserFeedback.created_at >= cutoff)
            .group_by(func.date(UserFeedback.created_at))
            .order_by(func.date(UserFeedback.created_at))
        )
        daily_feedback = [
            {"date": str(r.date), "count": r.count}
            for r in daily_result.all()
        ]

        # 7. Daily favorites trend
        daily_fav_result = await self.db.execute(
            select(
                func.date(FavoriteItem.created_at).label("date"),
                func.count().label("count"),
            )
            .where(
                FavoriteItem.target_type == FavoriteTargetType.CONTENT,
                FavoriteItem.created_at >= cutoff,
            )
            .group_by(func.date(FavoriteItem.created_at))
            .order_by(func.date(FavoriteItem.created_at))
        )
        daily_favorites = [
            {"date": str(r.date), "count": r.count}
            for r in daily_fav_result.all()
        ]

        # 8. Calculate rates
        favorite_rate = round(favorites_count / analyzed_count * 100, 1) if analyzed_count > 0 else 0
        ignore_rate = round(ignores_count / analyzed_count * 100, 1) if analyzed_count > 0 else 0
        feedback_rate = round(total_feedback / analyzed_count * 100, 1) if analyzed_count > 0 else 0

        return {
            "summary": {
                "analyzed_count": analyzed_count,
                "favorites_count": favorites_count,
                "ignores_count": ignores_count,
                "total_feedback": total_feedback,
                "favorite_rate": favorite_rate,
                "ignore_rate": ignore_rate,
                "feedback_rate": feedback_rate,
                "users_with_vectors": users_with_vectors,
            },
            "feedback_distribution": feedback_dist,
            "top_tags": top_tags,
            "daily_feedback": daily_feedback,
            "daily_favorites": daily_favorites,
        }
