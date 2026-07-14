"""
Shared context builders for periodical AI digests.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.duckdb_service import query_content_for_weekly
from app.services.scoring_engine import ScoringInput, score_items


async def fetch_analyzed_content(
    db: AsyncSession,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Fetch analyzed content and apply the unified scoring gate for digests."""
    _ = db
    return _score_digest_rows(query_content_for_weekly(start_date=start_date, end_date=end_date))


async def fetch_analyzed_content_with_expanded_window(
    db: AsyncSession,
    start_date: str,
    end_date: str,
    expanded_days: int,
) -> list[dict]:
    """Fetch a strict period first, then expand to a trailing window ending at end_date."""
    data = await fetch_analyzed_content(db, start_date, end_date)
    if data:
        return data

    expanded_start = (date.fromisoformat(end_date) - timedelta(days=expanded_days - 1)).isoformat()
    return await fetch_analyzed_content(db, expanded_start, end_date)


def _score_digest_rows(rows: list[dict]) -> list[dict]:
    """Re-score DuckDB digest candidates through the shared curation engine."""
    if not rows:
        return []

    row_map = {int(row["id"]): row for row in rows}
    scoring_inputs = [_row_to_scoring_input(row) for row in rows]
    scored = score_items(scoring_inputs)
    digest_rows: list[dict] = []
    for breakdown, scoring_input in scored:
        if not breakdown.selected:
            continue
        row = dict(row_map[scoring_input.content_id])
        row["adjusted_score"] = breakdown.final_score
        row["score_breakdown"] = breakdown.to_dict()
        digest_rows.append(row)
    return digest_rows


def _row_to_scoring_input(row: dict) -> ScoringInput:
    def value_or_default(value, default):
        return default if value is None else value

    return ScoringInput(
        content_id=int(row["id"]),
        title=row.get("title") or "",
        category=row.get("category"),
        source_name=row.get("source_name"),
        crawled_at=row.get("crawled_at"),
        curation_score=value_or_default(row.get("curation_score"), 0),
        info_density=value_or_default(row.get("info_density"), 50),
        actionability=value_or_default(row.get("actionability"), 50),
        source_weight=value_or_default(row.get("source_weight"), 50),
        creator_score=value_or_default(row.get("creator_score"), 0),
        viral_score=value_or_default(row.get("viral_score"), 0),
        freshness_score=value_or_default(row.get("freshness_score"), 50),
        quality_score=value_or_default(row.get("quality_score"), 0),
        hot_score=value_or_default(row.get("hot_score"), 0),
        risk_score=value_or_default(row.get("risk_score"), 0),
        source_weight_db=value_or_default(row.get("source_weight_db"), 3),
        feedback_score=value_or_default(row.get("feedback_score"), 0),
    )


def build_category_stats(items: list[dict]) -> dict[str, dict]:
    """Build category-level statistics from scored content items."""
    categories: dict[str, dict] = {}
    for item in items:
        category = item["category"]
        if category not in categories:
            categories[category] = {"count": 0, "scores": [], "titles": []}
        categories[category]["count"] += 1
        categories[category]["scores"].append(item["creator_score"])
        categories[category]["titles"].append(item["title"])
    return categories


def build_items_text(items: list[dict], limit: int = 25) -> str:
    """Build compact ranked item text for digest prompts."""
    lines = []
    for index, item in enumerate(items[:limit], 1):
        curation_score = item.get("adjusted_score", item.get("curation_score", 0))
        block = [
            f"{index}. [{item['category']}] {item['title']}",
            (
                f"   来源: {item['source_name']} | "
                f"精选:{curation_score:.0f} 创作:{item['creator_score']:.0f} "
                f"爆文:{item['viral_score']:.0f} 质量:{item['quality_score']:.0f} "
                f"风险:{item['risk_score']:.0f}"
            ),
        ]
        if item.get("summary"):
            block.append(f"   摘要: {item['summary'][:120]}")
        if item.get("recommendation"):
            block.append(f"   推荐语: {item['recommendation'][:80]}")
        lines.append("\n".join(block))
    return "\n" + "\n".join(lines) if lines else ""


def build_category_text(category_stats: dict[str, dict]) -> str:
    """Build compact category statistics text for digest prompts."""
    lines = []
    for category, info in sorted(category_stats.items(), key=lambda x: x[1]["count"], reverse=True):
        avg = sum(info["scores"]) / len(info["scores"]) if info["scores"] else 0
        lines.append(f"- {category}: {info['count']}篇, 平均创作分 {avg:.0f}, 热门: {info['titles'][0][:40]}")
    return "\n" + "\n".join(lines) if lines else ""
