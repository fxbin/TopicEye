"""Build read-only explanation payloads for the scoring funnel UI."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.content_repo import ContentRepo, ScoringContentRow
from app.repositories.ignored_repo import IgnoredRepo
from app.services.feedback_signal import get_feedback_scores
from app.services.json_cache import (
    get_cached_json as _get_cached_json,
    get_cached_value as _get_cached_value,
    invalidate_json_cache as _invalidate_json_cache,
    set_cached_json as _set_cached_json,
)
from app.services.scoring_engine import CONFIG, ScoreBreakdown, ScoringInput, score_items

STAGE_KEYS = ["candidates", "quality", "risk", "freshness", "diversity", "selected"]
STAGE_LABELS = ["候选样本", "质量门槛", "风险降权", "时效衰减", "多样性混排", "精选输出"]
DEBUG_WINDOW_HOURS = (24, 48, 168, 720)
DEFAULT_SCORING_FLOW_HOURS = 24
DEFAULT_SCORING_FLOW_LIMIT = 160
SCORING_FLOW_WARMUP_TARGETS = (
    (DEFAULT_SCORING_FLOW_HOURS, DEFAULT_SCORING_FLOW_LIMIT),
    (48, DEFAULT_SCORING_FLOW_LIMIT),
)
# Cache delegates to the shared json_cache with a "scoring_flow:" prefix.
# Eviction is invalidation-based (no TTL) — callers call
# invalidate_scoring_flow_cache() when content changes.
SCORING_FLOW_CACHE_PREFIX = "scoring_flow:"
# Eviction is invalidation-based; TTL is effectively infinite.
SCORING_FLOW_CACHE_TTL = float('inf')


def _cache_key_str(
    hours: int, limit: int, sample_limit: int, visible_user_id: int | None
) -> str:
    """Build a string cache key for json_cache (was tuple before migration)."""
    uid = visible_user_id if visible_user_id is not None else ""
    return f"{SCORING_FLOW_CACHE_PREFIX}hours={hours}&limit={limit}&sample={sample_limit}&uid={uid}"


def get_cached_scoring_flow_json(
    *,
    hours: int,
    limit: int,
    sample_limit: int = 80,
    visible_user_id: int | None = None,
) -> tuple[bytes, float] | None:
    """Return pre-serialized cached payload for hot scoring-flow requests."""
    key = _cache_key_str(hours, limit, sample_limit, visible_user_id)
    return _get_cached_json(key, ttl_seconds=SCORING_FLOW_CACHE_TTL)


def invalidate_scoring_flow_cache() -> None:
    _invalidate_json_cache(SCORING_FLOW_CACHE_PREFIX)


async def build_scoring_flow_payload(
    db: AsyncSession,
    *,
    hours: int,
    limit: int,
    sample_limit: int = 80,
    visible_user_id: int | None = None,
) -> dict[str, Any]:
    """Return scoring funnel stages, candidate samples, and mix pressure data."""
    key = _cache_key_str(hours, limit, sample_limit, visible_user_id)
    cached = _get_cached_value(key, ttl_seconds=SCORING_FLOW_CACHE_TTL)
    if cached:
        return cached[0]

    time_cutoff = datetime.now(UTC) - timedelta(hours=hours)
    ignored_ids = await IgnoredRepo(db).list_ignored_ids()
    content_repo = ContentRepo(db)
    window_counts = await build_window_counts(
        content_repo, ignored_ids, requested_hours=hours, visible_user_id=visible_user_id
    )
    collected_window_counts = await build_collected_window_counts(
        content_repo,
        ignored_ids,
        requested_hours=hours,
        visible_user_id=visible_user_id,
    )
    collected_window_total = next(
        (item["count"] for item in collected_window_counts if item["hours"] == hours),
        None,
    )
    if collected_window_total is None:
        collected_window_total = await content_repo.count_collected_for_scoring_window(
            exclude_ids=ignored_ids,
            time_cutoff=time_cutoff,
            visible_user_id=visible_user_id,
        )
    window_total = next(
        (item["count"] for item in window_counts if item["hours"] == hours),
        None,
    )
    if window_total is None:
        window_total = await content_repo.count_for_scoring(
            exclude_ids=ignored_ids,
            time_cutoff=time_cutoff,
            visible_user_id=visible_user_id,
        )
    if window_total <= 0:
        analyzed_total = await content_repo.count_for_scoring(
            exclude_ids=ignored_ids, visible_user_id=visible_user_id
        )
        payload = build_empty_payload(
            hours=hours,
            analyzed_total=analyzed_total,
            window_total=window_total,
            collected_window_total=collected_window_total,
            window_counts=window_counts,
            collected_window_counts=collected_window_counts,
            ignored_count=len(ignored_ids),
            limit=limit,
            sample_limit=sample_limit,
        )
        return _cache_and_return(hours, limit, sample_limit, visible_user_id, payload)

    analyzed_total = window_total
    items = await content_repo.list_scoring_rows(
        exclude_ids=ignored_ids,
        time_cutoff=time_cutoff,
        limit=limit,
        visible_user_id=visible_user_id,
    )

    scoring_inputs, item_map, feedback_scores = await build_scoring_inputs_from_rows(db, items)
    scored = score_items(scoring_inputs)

    category_counts = Counter((item.category or "未分类") for _, item in scored)
    source_counts = Counter((item.source_name or "未知来源") for _, item in scored)

    payload = {
        "total": window_total,
        "scored": len(scored),
        "hours": hours,
        "diagnostics": build_diagnostics(
            analyzed_total=analyzed_total,
            window_total=window_total,
            collected_window_total=collected_window_total,
            window_counts=window_counts,
            collected_window_counts=collected_window_counts,
            loaded_count=len(items),
            scoring_input_count=len(scoring_inputs),
            scored_count=len(scored),
            ignored_count=len(ignored_ids),
            limit=limit,
            sample_limit=sample_limit,
        ),
        "scoring_config": build_scoring_config_summary(),
        "stages": build_stage_counts(scored),
        "samples": [
            sample
            for breakdown, scoring_input in scored[:sample_limit]
            if (
                sample := build_sample_payload(
                    breakdown,
                    scoring_input,
                    item_map,
                    feedback_scores,
                )
            )
        ],
        "category_mix": [{"label": k, "count": v} for k, v in category_counts.most_common(8)],
        "source_mix": [{"label": k, "count": v} for k, v in source_counts.most_common(8)],
    }
    return _cache_and_return(hours, limit, sample_limit, visible_user_id, payload)


async def build_window_counts(
    content_repo: ContentRepo,
    ignored_ids: list[int],
    requested_hours: int | None = None,
    *,
    visible_user_id: int | None = None,
) -> list[dict[str, int]]:
    """Count analyzed candidates for the debug window selector."""
    now = datetime.now(UTC)
    counts: list[dict[str, int]] = []
    for hours in debug_window_hours(requested_hours):
        count = await content_repo.count_for_scoring(
            exclude_ids=ignored_ids,
            time_cutoff=now - timedelta(hours=hours),
            visible_user_id=visible_user_id,
        )
        counts.append({"hours": hours, "count": count})
    return counts


async def build_collected_window_counts(
    content_repo: ContentRepo,
    ignored_ids: list[int],
    requested_hours: int | None = None,
    *,
    visible_user_id: int | None = None,
) -> list[dict[str, int]]:
    """Count collected items for explaining pre-analysis gaps."""
    now = datetime.now(UTC)
    counts: list[dict[str, int]] = []
    for hours in debug_window_hours(requested_hours):
        count = await content_repo.count_collected_for_scoring_window(
            exclude_ids=ignored_ids,
            time_cutoff=now - timedelta(hours=hours),
            visible_user_id=visible_user_id,
        )
        counts.append({"hours": hours, "count": count})
    return counts


def debug_window_hours(requested_hours: int | None = None) -> tuple[int, ...]:
    """Return stable debug windows while preserving a custom requested window."""
    if requested_hours is None:
        return DEBUG_WINDOW_HOURS
    return tuple(sorted({*DEBUG_WINDOW_HOURS, requested_hours}))


def _cache_and_return(
    hours: int,
    limit: int,
    sample_limit: int,
    visible_user_id: int | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Store payload in the shared json_cache and return a cold copy.

    The cached copy gets ``cache.hit = True``; the returned cold copy gets
    ``cache.hit = False`` so the caller sees a fresh (non-cached) response.
    """
    cold_payload = dict(payload)
    cold_payload["cache"] = {
        "hit": False,
        "mode": "invalidation",
        "age_ms": 0,
    }
    cached_payload = dict(payload)
    cached_payload["cache"] = {
        "hit": True,
        "mode": "invalidation",
        "age_ms": 0,
    }
    key = _cache_key_str(hours, limit, sample_limit, visible_user_id)
    _set_cached_json(key, cached_payload)
    return cold_payload


async def build_scoring_inputs_from_rows(
    db: AsyncSession,
    items: list[ScoringContentRow],
) -> tuple[list[ScoringInput], dict[int, ScoringContentRow], dict[int, float]]:
    """Build scoring inputs from lightweight rows without ORM relationship loading."""
    feedback_scores = await get_feedback_scores(db, [item.id for item in items])
    scoring_inputs: list[ScoringInput] = []
    item_map: dict[int, ScoringContentRow] = {}

    for item in items:
        scoring_inputs.append(
            ScoringInput(
                content_id=item.id,
                title=item.title,
                category=item.category,
                source_id=item.source_id,
                source_name=item.source_name,
                published_at=item.published_at,
                crawled_at=item.crawled_at,
                curation_score=item.curation_score or 0,
                info_density=item.info_density or 50,
                actionability=item.actionability or 50,
                source_weight=item.source_weight or 50,
                creator_score=item.creator_score or 0,
                viral_score=item.viral_score or 0,
                freshness_score=item.freshness_score or 0,
                quality_score=item.quality_score or 0,
                hot_score=item.hot_score or 0,
                risk_score=item.risk_score or 0,
                source_weight_db=item.source_weight_db or 3,
                feedback_score=feedback_scores.get(item.id, 0),
            )
        )
        item_map[item.id] = item

    return scoring_inputs, item_map, feedback_scores


def build_empty_payload(
    *,
    hours: int,
    analyzed_total: int,
    window_total: int,
    ignored_count: int,
    limit: int,
    sample_limit: int,
    collected_window_total: int = 0,
    window_counts: list[dict[str, int]] | None = None,
    collected_window_counts: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Build a scoring-flow response without loading ORM rows when no samples exist."""
    return {
        "total": window_total,
        "scored": 0,
        "hours": hours,
        "diagnostics": build_diagnostics(
            analyzed_total=analyzed_total,
            window_total=window_total,
            collected_window_total=collected_window_total,
            window_counts=window_counts,
            collected_window_counts=collected_window_counts,
            loaded_count=0,
            scoring_input_count=0,
            scored_count=0,
            ignored_count=ignored_count,
            limit=limit,
            sample_limit=sample_limit,
        ),
        "scoring_config": build_scoring_config_summary(),
        "stages": build_stage_counts([]),
        "samples": [],
        "category_mix": [],
        "source_mix": [],
    }


def build_diagnostics(
    *,
    analyzed_total: int,
    window_total: int,
    loaded_count: int,
    scoring_input_count: int,
    scored_count: int,
    ignored_count: int,
    limit: int,
    sample_limit: int,
    collected_window_total: int = 0,
    window_counts: list[dict[str, int]] | None = None,
    collected_window_counts: list[dict[str, int]] | None = None,
) -> dict[str, Any]:
    """Explain why the scoring-flow payload is empty or partial."""
    if collected_window_total > 0 and window_total <= 0:
        empty_reason = "collected_not_analyzed"
    elif analyzed_total <= 0:
        empty_reason = "no_analyzed_content"
    elif window_total <= 0:
        empty_reason = "no_content_in_window"
    elif loaded_count <= 0:
        empty_reason = "candidate_limit_empty"
    elif scoring_input_count <= 0:
        empty_reason = "no_scoring_inputs"
    elif scored_count <= 0:
        empty_reason = "all_candidates_filtered"
    else:
        empty_reason = "ok"

    normalized_window_counts = window_counts or []
    recommended_hours = next(
        (item["hours"] for item in normalized_window_counts if item.get("count", 0) > 0),
        None,
    )

    return {
        "analyzed_total": analyzed_total,
        "window_total": window_total,
        "collected_window_total": collected_window_total,
        "pending_analysis_total": max(0, collected_window_total - window_total),
        "window_options": normalized_window_counts,
        "collected_window_options": collected_window_counts or [],
        "recommended_hours": recommended_hours,
        "loaded_count": loaded_count,
        "scoring_input_count": scoring_input_count,
        "scored_count": scored_count,
        "ignored_count": ignored_count,
        "candidate_limit": limit,
        "sample_limit": sample_limit,
        "empty_reason": empty_reason,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def build_scoring_config_summary() -> dict[str, Any]:
    """Expose stable scoring knobs for UI explanation, not mutation."""
    keys = (
        "curation_mode",
        "curation_percentile",
        "curation_threshold",
        "min_selected_base_score",
        "quality_gate_min",
        "quality_gate_strong",
        "quality_gate_floor",
        "risk_threshold",
        "risk_soft_start",
        "risk_soft_floor",
        "time_decay_lambda",
        "time_decay_floor",
        "diversity_top_n",
        "same_source_grace",
        "same_category_grace",
    )
    return {key: CONFIG[key] for key in keys}


def build_stage_counts(scored: list[tuple[ScoreBreakdown, ScoringInput]]) -> list[dict[str, Any]]:
    total = len(scored)
    quality_pass = [(breakdown, item) for breakdown, item in scored if breakdown.quality_factor > 0.55]
    risk_pass = [(breakdown, item) for breakdown, item in quality_pass if breakdown.risk_factor > 0.55]
    freshness_pass = [(breakdown, item) for breakdown, item in risk_pass if breakdown.time_decay > 0]
    diversity_pass = [(breakdown, item) for breakdown, item in freshness_pass if breakdown.diversity_factor > 0]
    selected = [(breakdown, item) for breakdown, item in diversity_pass if breakdown.selected]
    counts = [total, len(quality_pass), len(risk_pass), len(freshness_pass), len(diversity_pass), len(selected)]
    return [
        {
            "key": key,
            "label": label,
            "count": count,
            "retention": round(count / total, 4) if total else 0,
        }
        for key, label, count in zip(STAGE_KEYS, STAGE_LABELS, counts, strict=False)
    ]


def build_sample_payload(
    breakdown: ScoreBreakdown,
    scoring_input: ScoringInput,
    item_map: dict[int, Any],
    feedback_scores: dict[int, float],
) -> dict[str, Any] | None:
    item = item_map.get(scoring_input.content_id)
    if not item:
        return None
    return {
        "id": item.id,
        "title": item.title,
        "url": item.url,
        "source_name": item.source_name,
        "category": item.category or "未分类",
        "summary": first_text(getattr(item, "ai_summary", None), getattr(item, "summary", None)),
        "recommendation": first_text(
            getattr(item, "recommendation", None),
            getattr(item, "recommended_reason", None),
        ),
        "tags": string_list(getattr(item, "analysis_tags", None)) or string_list(getattr(item, "tags", None)),
        "creator_angles": string_list(getattr(item, "creator_angles", None)),
        "is_favorited": bool(getattr(item, "is_favorited", False)),
        "selected": breakdown.selected,
        "final_score": breakdown.final_score,
        "threshold_used": breakdown.threshold_used,
        "base_score": breakdown.base_score,
        "source_bonus": breakdown.source_bonus,
        "quality_factor": breakdown.quality_factor,
        "risk_factor": breakdown.risk_factor,
        "time_decay": breakdown.time_decay,
        "diversity_factor": breakdown.diversity_factor,
        "feedback_score": feedback_scores.get(item.id, 0),
        "dimension_scores": breakdown.dimension_scores,
    }


def first_text(*values: str | None) -> str | None:
    for value in values:
        if value and value.strip():
            return value.strip()
    return None


def string_list(value: Any) -> list[str]:
    items: list[str] = []

    def visit(raw: Any) -> None:
        if raw is None:
            return
        if isinstance(raw, str):
            items.extend(part.strip() for part in raw.split(",") if part.strip())
            return
        if isinstance(raw, dict):
            for child in raw.values():
                visit(child)
            return
        if isinstance(raw, list | tuple | set):
            for child in raw:
                visit(child)
            return
        text = str(raw).strip()
        if text:
            items.append(text)

    visit(value)
    return list(dict.fromkeys(items))
