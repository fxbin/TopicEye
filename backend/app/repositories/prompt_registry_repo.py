"""Read the code-template catalog and aggregate request attempts once per scene."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select

from app.models.llm_model import LlmCallLog
from app.models.prompt_registry import PromptRegistry
from app.repositories.base import BaseRepository


def _prompt_item(prompt: PromptRegistry) -> dict[str, Any]:
    return {
        "id": prompt.id,
        "name": prompt.name,
        "scene": prompt.scene,
        "description": prompt.description,
        "source_file": prompt.source_file,
        "content_preview": prompt.content_preview,
        "version_hash": prompt.version_hash[:8],
        "updated_at": prompt.updated_at.isoformat() if prompt.updated_at else None,
    }


def _stats(row) -> dict[str, Any]:
    return {
        "call_count": row.call_count or 0,
        "success_count": row.success_count or 0,
        "failed_count": row.failed_count or 0,
        "other_count": (row.call_count or 0) - (row.success_count or 0) - (row.failed_count or 0),
        "total_cost": round(float(row.total_cost or 0), 4),
        "total_input_tokens": row.total_input_tokens or 0,
        "total_output_tokens": row.total_output_tokens or 0,
        "avg_duration_ms": round(float(row.avg_duration_ms or 0)),
    }


def _aggregate_columns():
    return (
        func.count().label("call_count"),
        func.count().filter(LlmCallLog.status == "DONE").label("success_count"),
        func.count().filter(LlmCallLog.status == "FAILED").label("failed_count"),
        func.sum(LlmCallLog.total_cost).label("total_cost"),
        func.sum(LlmCallLog.input_tokens).label("total_input_tokens"),
        func.sum(LlmCallLog.output_tokens).label("total_output_tokens"),
        func.avg(LlmCallLog.duration_ms).label("avg_duration_ms"),
    )


_EMPTY_STATS = {
    "call_count": 0,
    "success_count": 0,
    "failed_count": 0,
    "other_count": 0,
    "total_cost": 0,
    "total_input_tokens": 0,
    "total_output_tokens": 0,
    "avg_duration_ms": 0,
}
ATTRIBUTION = {
    "unit": "scene_request_attempt",
    "versions": "all",
    "template_version_attribution": False,
    "retry_count": None,
    "response_cache_hits": None,
}


class PromptRegistryRepository(BaseRepository[PromptRegistry]):
    model = PromptRegistry

    async def catalog_with_stats(self, *, scene: str | None, stats_cutoff: datetime, active_names: set[str]):
        stmt = (
            select(PromptRegistry)
            .where(PromptRegistry.name.in_(active_names))
            .order_by(PromptRegistry.scene, PromptRegistry.name)
        )
        if scene:
            stmt = stmt.where(PromptRegistry.scene == scene)
        prompts = (await self.db.execute(stmt)).scalars().all()
        calls = select(LlmCallLog.scene, *_aggregate_columns()).where(LlmCallLog.created_at >= stats_cutoff)
        if scene:
            calls = calls.where(LlmCallLog.scene == scene)
        statistics = {r.scene: _stats(r) for r in (await self.db.execute(calls.group_by(LlmCallLog.scene))).all()}
        items = [_prompt_item(prompt) for prompt in prompts]
        scenes = sorted({p.scene for p in prompts} | set(statistics))
        return {
            "items": items,
            "total": len(items),
            "attribution": ATTRIBUTION,
            "scenes": [
                {
                    "scene": name,
                    "template_count": sum(p.scene == name for p in prompts),
                    "stats_7d": statistics.get(name, dict(_EMPTY_STATS)),
                }
                for name in scenes
            ],
        }

    async def get_detail_with_stats(
        self, *, prompt_id: int, stats_cutoff: datetime, active_names: set[str] | None = None
    ):
        stmt = select(PromptRegistry).where(PromptRegistry.id == prompt_id)
        if active_names is not None:
            stmt = stmt.where(PromptRegistry.name.in_(active_names))
        prompt = (await self.db.execute(stmt)).scalar_one_or_none()
        if prompt is None:
            return None
        conditions = (LlmCallLog.scene == prompt.scene, LlmCallLog.created_at >= stats_cutoff)
        row = (await self.db.execute(select(*_aggregate_columns()).where(*conditions))).one()
        daily = (
            await self.db.execute(
                select(func.date(LlmCallLog.created_at).label("date"), *_aggregate_columns())
                .where(*conditions)
                .group_by(func.date(LlmCallLog.created_at))
                .order_by(func.date(LlmCallLog.created_at))
            )
        ).all()
        return {
            **_prompt_item(prompt),
            "version_hash": prompt.version_hash,
            "full_content": prompt.full_content,
            "attribution": ATTRIBUTION,
            "stats_30d": _stats(row),
            "daily_trend": [{"date": str(r.date), **_stats(r)} for r in daily],
        }
