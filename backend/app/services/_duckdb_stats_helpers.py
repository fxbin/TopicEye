"""DuckDB stats 辅助纯函数（从 DuckDBAnalytics 静态方法抽出）。

包含 5 个纯函数：
- stats_row_to_scoring_input   将 stats 查询行转为 ScoringInput
- stats_threshold_from_scored  从 scored_items 提取 curation 阈值
- selected_stats_items         过选出 selected=True 的 items
- stats_date_key               日期键标准化
- stats_source_key             信源键标准化
"""

from __future__ import annotations

from typing import Any

from app.services._duckdb_sql import STATS_CURATION_FALLBACK_THRESHOLD
from app.services.scoring_engine import ScoringInput


def stats_row_to_scoring_input(row: dict[str, Any]) -> ScoringInput:
    return ScoringInput(
        content_id=row["id"],
        title="",
        category=row.get("category"),
        source_id=row.get("source_id"),
        source_name=row.get("source_name"),
        crawled_at=row.get("crawled_at"),
        curation_score=row.get("curation_score") or 0,
        info_density=row.get("info_density") or 50,
        actionability=row.get("actionability") or 50,
        source_weight=row.get("analysis_source_weight") or 50,
        creator_score=row.get("creator_score") or 0,
        viral_score=row.get("viral_score") or 0,
        freshness_score=row.get("freshness_score") or 0,
        quality_score=row.get("quality_score") or 0,
        hot_score=row.get("hot_score") or 0,
        risk_score=row.get("risk_score") or 0,
        source_weight_db=row.get("source_weight_db") or 3,
        feedback_score=row.get("feedback_score") or 0,
    )


def stats_threshold_from_scored(scored_items: list[dict[str, Any]]) -> float:
    for item in scored_items:
        threshold = item.get("threshold_used")
        if threshold is not None:
            return round(float(threshold), 1)
    return STATS_CURATION_FALLBACK_THRESHOLD


def selected_stats_items(scored_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [item for item in scored_items if item.get("selected")]


def stats_date_key(value: Any) -> str:
    if hasattr(value, "date"):
        return value.date().isoformat()
    return str(value).split(" ")[0]


def stats_source_key(item: dict[str, Any]) -> tuple[str, str]:
    return (item.get("source_name") or "未知", item.get("source_type") or "unknown")
