"""Repository for PromptRegistry and LlmCallLog aggregated reads."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models.llm_model import LlmCallLog
from app.models.prompt_registry import PromptRegistry
from app.repositories.base import BaseRepository


class PromptRegistryRepository(BaseRepository[PromptRegistry]):
    model = PromptRegistry

    async def list_with_stats(
        self,
        scene: str | None,
        stats_cutoff: datetime,
    ) -> list[dict[str, Any]]:
        """List prompts joined with 7-day LlmCallLog stats."""
        stmt = select(PromptRegistry).order_by(PromptRegistry.scene, PromptRegistry.name)
        if scene:
            stmt = stmt.where(PromptRegistry.scene == scene)
        result = await self.db.execute(stmt)
        prompts = result.scalars().all()

        # Batch query: call counts per scene in last 7 days
        stats_result = await self.db.execute(
            select(
                LlmCallLog.scene,
                func.count().label("call_count"),
                func.sum(LlmCallLog.total_cost).label("total_cost"),
                func.avg(LlmCallLog.duration_ms).label("avg_duration_ms"),
            )
            .where(LlmCallLog.created_at >= stats_cutoff)
            .group_by(LlmCallLog.scene)
        )
        stats_map: dict[str, dict[str, Any]] = {}
        for row in stats_result.all():
            stats_map[row.scene] = {
                "call_count_7d": row.call_count,
                "total_cost_7d": round(float(row.total_cost or 0), 4),
                "avg_duration_ms_7d": round(float(row.avg_duration_ms or 0), 0),
            }

        items = []
        for p in prompts:
            s = stats_map.get(p.scene, {})
            items.append(
                {
                    "id": p.id,
                    "name": p.name,
                    "scene": p.scene,
                    "description": p.description,
                    "source_file": p.source_file,
                    "content_preview": p.content_preview,
                    "version_hash": p.version_hash[:8] if p.version_hash else "",
                    "updated_at": p.updated_at.isoformat() if p.updated_at else None,
                    "stats_7d": s,
                }
            )
        return items

    async def get_detail_with_stats(
        self,
        prompt_id: int,
        stats_cutoff: datetime,
    ) -> dict[str, Any] | None:
        """Get a single prompt with 30-day usage stats and daily trend."""
        result = await self.db.execute(select(PromptRegistry).where(PromptRegistry.id == prompt_id))
        prompt = result.scalar_one_or_none()
        if prompt is None:
            return None

        # 30-day aggregate stats
        stats_result = await self.db.execute(
            select(
                func.count().label("call_count"),
                func.sum(LlmCallLog.total_cost).label("total_cost"),
                func.sum(LlmCallLog.input_tokens).label("total_input_tokens"),
                func.sum(LlmCallLog.output_tokens).label("total_output_tokens"),
                func.avg(LlmCallLog.duration_ms).label("avg_duration_ms"),
            )
            .where(LlmCallLog.scene == prompt.scene)
            .where(LlmCallLog.created_at >= stats_cutoff)
        )
        row = stats_result.one()

        # Daily breakdown for trend
        daily_result = await self.db.execute(
            select(
                func.date(LlmCallLog.created_at).label("date"),
                func.count().label("calls"),
                func.sum(LlmCallLog.total_cost).label("cost"),
            )
            .where(LlmCallLog.scene == prompt.scene)
            .where(LlmCallLog.created_at >= stats_cutoff)
            .group_by(func.date(LlmCallLog.created_at))
            .order_by(func.date(LlmCallLog.created_at))
        )
        daily = [
            {
                "date": str(r.date),
                "calls": r.calls,
                "cost": round(float(r.cost or 0), 4),
            }
            for r in daily_result.all()
        ]

        return {
            "id": prompt.id,
            "name": prompt.name,
            "scene": prompt.scene,
            "description": prompt.description,
            "source_file": prompt.source_file,
            "full_content": prompt.full_content,
            "version_hash": prompt.version_hash,
            "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
            "stats_30d": {
                "call_count": row.call_count or 0,
                "total_cost": round(float(row.total_cost or 0), 4),
                "total_input_tokens": row.total_input_tokens or 0,
                "total_output_tokens": row.total_output_tokens or 0,
                "avg_duration_ms": round(float(row.avg_duration_ms or 0), 0),
            },
            "daily_trend": daily,
        }
