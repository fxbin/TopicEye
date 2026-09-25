from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ranking_eval import RankingEvalSnapshot


class RankingEvalRepository:
    """排序评测快照的唯一 ORM 入口。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_snapshot(
        self,
        *,
        surface: str,
        window_start: datetime,
        window_end: datetime,
        metrics: dict,
        scoring_config: dict,
        item_details: dict | None = None,
    ) -> RankingEvalSnapshot:
        """同一 (surface, window_start) 重复评测时覆盖更新（保留最新口径）。"""
        stmt = (
            pg_insert(RankingEvalSnapshot)
            .values(
                surface=surface,
                window_start=window_start,
                window_end=window_end,
                metrics=metrics,
                scoring_config=scoring_config,
                item_details=item_details,
                created_at=datetime.now(UTC),
            )
            .on_conflict_do_update(
                constraint="uq_eval_surface_window",
                set_={
                    "window_end": window_end,
                    "metrics": metrics,
                    "scoring_config": scoring_config,
                    "item_details": item_details,
                },
            )
            .returning(RankingEvalSnapshot)
        )
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.scalar_one()

    async def list_snapshots(
        self,
        *,
        surface: str | None = None,
        limit: int = 30,
    ) -> Sequence[RankingEvalSnapshot]:
        stmt = select(RankingEvalSnapshot).order_by(RankingEvalSnapshot.window_start.desc()).limit(limit)
        if surface:
            stmt = stmt.where(RankingEvalSnapshot.surface == surface)
        result = await self.db.execute(stmt)
        return result.scalars().all()
