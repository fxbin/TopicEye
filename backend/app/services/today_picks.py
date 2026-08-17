"""Today-picks business logic backed by DuckDB analytical reads."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.content import ContentItem
from app.repositories.content_event_consumption_repo import (
    ContentEventConsumptionRepository,
    EventAssignment,
    EventDisplayGroup,
)
from app.repositories.ignored_repo import IgnoredRepo
from app.services.content_summary import clean_content_summary
from app.services.duckdb_service import query_today_picks, query_topics, run_query
from app.services.feedback_signal import get_feedback_scores
from app.services.scoring_engine import CONFIG as SCORING_CONFIG, ScoreBreakdown, ScoringInput, score_items

logger = logging.getLogger(__name__)

# 与 DuckDB query_today_picks 的 weight_bonus 默认值（duckdb_service.py）一致，
# fallback 复刻 adjusted_curation_score 排序时使用。
_OLTP_FALLBACK_WEIGHT_BONUS = 8


async def build_today_picks(
    db: AsyncSession,
    *,
    category: str | None = None,
    content_type: str | None = None,
    hours: int = 48,
    limit: int | None = None,
    owner_user_id: int | None = None,
) -> dict:
    """Return today-picks payload through DuckDB, with OLTP fallback.

    首选 DuckDB（OLTP schema 通过 ATTACH 直接读，含 feedback_score 聚合、
    source_weight 加成、ignored 过滤）。

    若 DuckDB 不可用（扩展缺失、ATTACH 失败、host 无法解析等），降级到
    ``_build_today_picks_via_oltp``：走 SQLAlchemy 拉 ContentItem + analyses，
    输出与 DuckDB 路径**完全一致**的 row dict 结构，便于 scoring / payload
    构造代码复用。降级路径复刻 DuckDB 的 ignored / feedback_score /
    source_weight 加成 / 风险门口径，保证两条路径行为等价。
    """
    duckdb_exc: Exception | None = None
    try:
        query_kwargs = {
            "hours": hours,
            "category": category,
            "content_type": content_type,
            "limit": limit,
            # DuckDB supplies candidates; the unified scorer below is the only final gate.
            "curation_threshold": 0,
        }
        if owner_user_id is not None:
            query_kwargs["visible_user_id"] = owner_user_id
            query_kwargs["public_only"] = False
        rows = await run_query(lambda: query_today_picks(**query_kwargs))
    except Exception as exc:
        duckdb_exc = exc
        logger.warning(
            "today_picks DuckDB analytical layer unavailable, falling back to OLTP query: %s",
            exc,
            exc_info=True,
        )
        try:
            rows = await _build_today_picks_via_oltp(
                db,
                hours=hours,
                category=category,
                content_type=content_type,
                limit=limit,
                owner_user_id=owner_user_id,
            )
        except Exception as oltp_exc:
            # OLTP 路径也挂了：记双错误，回退到空 payload（避免 5xx）
            logger.error(
                "today_picks OLTP fallback also failed: %s (original DuckDB error: %s)",
                oltp_exc,
                duckdb_exc,
                exc_info=True,
            )
            return _empty_payload()

    event_repo = ContentEventConsumptionRepository(db)
    try:
        event_assignments = await event_repo.resolve_today_pick_assignments(
            (row["id"] for row in rows if row.get("id") is not None),
            visible_user_id=owner_user_id,
        )
    except Exception:
        logger.exception("Today-picks event truth unavailable")
        return _empty_payload()

    working_rows = _apply_event_assignments(rows, event_assignments)
    hidden_member_count = len(rows) - len(working_rows)

    scored_rows = _score_rows(working_rows)
    if not scored_rows:
        return _empty_payload()

    # The scorer still sees the entire candidate pool (needed for percentile
    # selection), while the response only materializes the requested first page.
    # Previously all selected rows were converted into full content payloads and
    # then truncated, making the default page transfer and render hundreds of
    # cards even when the UI only needed its first screen.
    total = len(scored_rows)
    visible_rows = scored_rows[:limit] if limit else scored_rows
    response_items = [_row_to_content_payload(row, breakdown) for breakdown, row in visible_rows]
    try:
        visible_group_ids = {
            assignment.event_group_id
            for item in response_items
            if (assignment := event_assignments.get(int(item["id"]))) is not None and assignment.is_canonical
        }
        event_groups = await event_repo.load_display_groups(
            visible_group_ids,
            visible_user_id=owner_user_id,
            member_limit=5,
        )
        _attach_event_normalization(
            response_items,
            event_assignments,
            event_groups,
        )
    except Exception:
        logger.warning(
            "Today-picks event expansion unavailable; canonical cards preserved",
            exc_info=True,
        )

    # Apply personalization boost (async, non-blocking for new users)
    if owner_user_id is not None:
        from app.services.interest_vector_service import apply_personalization_boost

        response_items = await apply_personalization_boost(db, owner_user_id, response_items)
        # Re-sort by boosted adjusted_curation_score
        response_items.sort(
            key=lambda item: (item.get("analysis") or {}).get("adjusted_curation_score", 0),
            reverse=True,
        )
    else:
        for item in response_items:
            item["personalization_boost"] = 0.0
    try:
        topic_map = {topic["id"]: topic for topic in await run_query(query_topics)}
    except Exception as exc:
        # topics 拉取失败：不阻塞主结果，只是不带话题关联
        logger.warning("today_picks query_topics failed, continuing without topics: %s", exc, exc_info=True)
        topic_map = {}

    return _pack_today_picks(
        response_items,
        topic_map,
        total=total,
        event_members_hidden=hidden_member_count,
    )


async def _build_today_picks_via_oltp(
    db: AsyncSession,
    *,
    hours: int,
    category: str | None,
    content_type: str | None = None,
    limit: int | None,
    owner_user_id: int | None = None,
) -> list[dict]:
    """OLTP fallback：直接走 SQLAlchemy 拉 ContentItem + analyses，
    输出与 ``query_today_picks`` 一致的 row dict，便于 scoring 复用。

    口径与 DuckDB 主路径对齐（避免 DuckDB 不可用时结果漂移）:
    - ignored 过滤：复用 IgnoredRepo.list_ignored_ids() 做 NOT IN
    - 风险门：取 SCORING_CONFIG["risk_threshold"]（与 DuckDB SQL 及 scorer 一致）
    - 事件成员：由统一事件真源批量过滤，不读取旧去重字段
    - feedback_score：复用 get_feedback_scores（latest-per-user → SUM，同 DuckDB CTE）
    - adjusted_curation_score：复刻 DuckDB 排序公式，保证候选顺序一致
    - 读取完整时间窗候选集，再由统一 scorer 决定最终入选；避免降级后因
      任意截断而遗漏本应进入 P70 的内容
    """
    cutoff = datetime.now(UTC) - timedelta(hours=hours)
    risk_threshold = float(SCORING_CONFIG["risk_threshold"])
    ignored_ids = await IgnoredRepo(db).list_ignored_ids()

    stmt = (
        select(ContentItem)
        .options(
            selectinload(ContentItem.analyses),
            selectinload(ContentItem.source),
        )
        .where(ContentItem.crawled_at >= cutoff)
        .order_by(ContentItem.crawled_at.desc())
    )
    if category:
        stmt = stmt.where(ContentItem.category == category)
    if content_type:
        stmt = stmt.where(ContentItem.content_type == content_type)
    if owner_user_id is None:
        stmt = stmt.where(ContentItem.owner_user_id.is_(None))
    else:
        stmt = stmt.where(
            or_(
                ContentItem.owner_user_id.is_(None),
                ContentItem.owner_user_id == owner_user_id,
            )
        )
    if ignored_ids:
        stmt = stmt.where(ContentItem.id.notin_(ignored_ids))

    result = await db.execute(stmt)
    items = result.scalars().unique().all()

    # 先按风险门 / curation 预筛（与 DuckDB SQL where 子句一致）
    eligible: list[ContentItem] = []
    for item in items:
        if not item.analyses:
            continue
        # analyses 关系已按 (created_at, id) 排序（model 端配置）
        latest = item.analyses[-1]
        if latest.curation_score is None:
            continue
        if latest.risk_score is not None and latest.risk_score > risk_threshold:
            continue
        eligible.append(item)

    # feedback 聚合（与 DuckDB LATEST_FEEDBACK_SCORES_CTE 同口径）
    feedback_scores = await get_feedback_scores(db, [item.id for item in eligible])

    feedback_min = float(SCORING_CONFIG["feedback_score_min"])
    feedback_max = float(SCORING_CONFIG["feedback_score_max"])
    feedback_weight = float(SCORING_CONFIG["w_feedback"])
    weight_bonus = _OLTP_FALLBACK_WEIGHT_BONUS

    rows: list[dict] = []
    for item in eligible:
        latest = item.analyses[-1]
        source = item.source
        source_weight_db = source.weight if source else 3
        feedback_score = feedback_scores.get(item.id, 0)

        curation_score = latest.curation_score or 0
        # 复刻 DuckDB adjusted_curation_score 排序公式
        feedback_clamped = min(max(feedback_score, feedback_min), feedback_max)
        adjusted_curation_score = (
            curation_score + (source_weight_db - 3) * weight_bonus + feedback_clamped * feedback_weight
        )

        rows.append(
            {
                "id": item.id,
                "title": item.title or "",
                "url": item.url or "",
                "source_id": item.source_id,
                "source_name": source.name if source else None,
                "source_type": str(item.source_type) if item.source_type else None,
                "platform": None,
                "author": None,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "crawled_at": item.crawled_at.isoformat() if item.crawled_at else None,
                "content_hash": item.content_hash,
                "summary": item.summary,
                "raw_content": item.raw_content,
                "cover_url": item.cover_url,
                "category": item.category,
                "content_type": item.content_type,
                "tags": item.tags,
                "language": item.language,
                "status": str(item.status) if item.status else "analyzed",
                "is_favorited": bool(item.is_favorited),
                "topic_id": item.topic_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "updated_at": item.updated_at.isoformat() if item.updated_at else None,
                "analysis_id": latest.id,
                "analysis_created_at": latest.created_at.isoformat(),
                "quality_score": latest.quality_score or 0,
                "hot_score": latest.hot_score or 0,
                "freshness_score": latest.freshness_score or 0,
                "creator_score": latest.creator_score or 0,
                "viral_score": latest.viral_score or 0,
                "risk_score": latest.risk_score or 0,
                "curation_score": curation_score,
                "info_density": latest.info_density or 0,
                "actionability": latest.actionability or 0,
                "recommended_reason": latest.recommended_reason,
                "recommendation": latest.recommendation,
                "ai_summary": latest.summary,
                "ai_tags": latest.tags,
                "key_points": latest.key_points,
                "audience_emotion": latest.audience_emotion,
                "creator_angles": latest.creator_angles,
                "title_suggestions": latest.title_suggestions,
                "outline_suggestions": latest.outline_suggestions,
                "xiaohongshu_plan": latest.xiaohongshu_plan,
                "short_video_plan": latest.short_video_plan,
                "risk_notes": latest.risk_notes,
                "platform_fit": latest.platform_fit,
                "summary_source": latest.summary_source,
                "enrichment_status": latest.enrichment_status,
                "enrichment": latest.enrichment,
                "analysis_source_weight": latest.source_weight,
                "source_weight_db": source_weight_db,
                "feedback_score": feedback_score,
                "adjusted_curation_score": adjusted_curation_score,
            }
        )
    return rows


def _empty_payload() -> dict:
    return {
        "items": [],
        "total": 0,
        "event_members_hidden": 0,
        "topics": [],
        "page": 1,
        "page_size": 0,
    }


def _score_rows(rows: list[dict]) -> list[tuple[ScoreBreakdown, dict]]:
    input_rows: list[tuple[ScoringInput, dict]] = [(_row_to_scoring_input(row), row) for row in rows]
    row_map = {item.content_id: row for item, row in input_rows}
    scored = score_items([item for item, _row in input_rows])
    # breakdown.selected 已包含所有 gate（curation threshold / min base score /
    # quality_factor / risk_factor）。score_items 内部按 CONFIG["curation_mode"]
    # 决定用固定阈值还是百分位阈值；percentile 模式下实际阈值可能是 18
    # （P70 of all final_scores），再用硬编码 55 兜底会把 percentile 选出来的
    # 全部过滤掉。直接用 breakdown.selected 即可。
    return [(breakdown, row_map[item.content_id]) for breakdown, item in scored if breakdown.selected]


def _row_to_scoring_input(row: dict) -> ScoringInput:
    def value_or_default(value, default):
        return default if value is None else value

    source_weight = row.get("analysis_source_weight")
    if source_weight is None:
        source_weight = row.get("source_weight")
    return ScoringInput(
        content_id=row["id"],
        title=row.get("title") or "",
        category=row.get("category"),
        source_id=row.get("source_id"),
        source_name=row.get("source_name"),
        published_at=row.get("published_at"),
        crawled_at=row.get("crawled_at"),
        curation_score=value_or_default(row.get("curation_score"), 0),
        info_density=value_or_default(row.get("info_density"), 50),
        actionability=value_or_default(row.get("actionability"), 50),
        source_weight=value_or_default(source_weight, 50),
        creator_score=value_or_default(row.get("creator_score"), 0),
        viral_score=value_or_default(row.get("viral_score"), 0),
        freshness_score=value_or_default(row.get("freshness_score"), 0),
        quality_score=value_or_default(row.get("quality_score"), 0),
        hot_score=value_or_default(row.get("hot_score"), 0),
        risk_score=value_or_default(row.get("risk_score"), 0),
        source_weight_db=value_or_default(row.get("source_weight_db"), 3),
        feedback_score=value_or_default(row.get("feedback_score"), 0),
    )


def _row_to_content_payload(row: dict, breakdown: ScoreBreakdown) -> dict:
    content_tags = _decode_json_value(row.get("tags"))
    analysis_tags = _decode_json_value(row.get("ai_tags")) or content_tags
    enrichment = _decode_json_value(row.get("enrichment"))
    score_breakdown = breakdown.to_dict()
    analysis = {
        "id": row.get("analysis_id") or 0,
        "content_id": row["id"],
        "quality_score": row.get("quality_score") or 0,
        "hot_score": row.get("hot_score") or 0,
        "freshness_score": row.get("freshness_score") or 0,
        "creator_score": row.get("creator_score") or 0,
        "viral_score": row.get("viral_score") or 0,
        "risk_score": row.get("risk_score") or 0,
        "platform_fit": _decode_json_value(row.get("platform_fit")),
        # Historical AI analyses may have copied RSS/Atom HTML from the
        # original summary.  These fields are displayed directly in the
        # today-picks analysis drawer, so normalise them at this read-model
        # boundary as well as ContentItem.summary below.
        "recommended_reason": _clean_optional_text(row.get("recommended_reason")),
        "summary": _clean_optional_text(row.get("ai_summary")),
        "key_points": _clean_text_list(row.get("key_points")),
        "audience_emotion": _clean_optional_text(row.get("audience_emotion")),
        "creator_angles": _clean_text_list(row.get("creator_angles")),
        "title_suggestions": _clean_text_list(row.get("title_suggestions")),
        "outline_suggestions": _clean_text_list(row.get("outline_suggestions")),
        "xiaohongshu_plan": _decode_json_value(row.get("xiaohongshu_plan")),
        "short_video_plan": _decode_json_value(row.get("short_video_plan")),
        "risk_notes": _decode_json_value(row.get("risk_notes")),
        "curation_score": row.get("curation_score") or 0,
        "tags": analysis_tags,
        "recommendation": _clean_optional_text(row.get("recommendation")),
        "info_density": row.get("info_density") or 0,
        "actionability": row.get("actionability") or 0,
        "source_weight": row.get("analysis_source_weight") or row.get("source_weight") or 0,
        "enrichment_status": row.get("enrichment_status") or "pending",
        "enrichment": enrichment,
        "created_at": row.get("analysis_created_at") or row.get("created_at") or datetime.now(UTC).isoformat(),
        "adjusted_curation_score": score_breakdown["final_score"],
        "score_breakdown": score_breakdown,
    }
    return {
        "id": row["id"],
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "source_id": row.get("source_id"),
        "source_name": row.get("source_name"),
        "source_type": row.get("source_type"),
        "platform": row.get("platform"),
        "author": row.get("author"),
        "published_at": row.get("published_at"),
        "crawled_at": row.get("crawled_at"),
        "content_hash": row.get("content_hash"),
        "summary": clean_content_summary(row.get("summary")),
        "cover_url": row.get("cover_url"),
        "category": row.get("category"),
        "content_type": row.get("content_type"),
        "tags": content_tags,
        "language": row.get("language"),
        "status": row.get("status") or "analyzed",
        "is_favorited": bool(row.get("is_favorited")),
        "created_at": row.get("created_at"),
        "updated_at": row.get("updated_at"),
        "topic_id": row.get("topic_id"),
        "analysis": analysis,
    }


def _decode_json_value(value):
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    if not stripped or stripped == "null":
        return None
    if stripped[0] not in "[{":
        return value
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return value


def _clean_optional_text(value):
    """Clean a rendered text field while preserving non-text/absent values."""
    return clean_content_summary(value) if isinstance(value, str) else value


def _clean_text_list(value):
    """Decode and clean a rendered string list, dropping metadata-only rows."""
    decoded = _decode_json_value(value)
    if not isinstance(decoded, list):
        return decoded

    cleaned: list = []
    for item in decoded:
        if not isinstance(item, str):
            cleaned.append(item)
            continue
        text = clean_content_summary(item)
        if text:
            cleaned.append(text)
    return cleaned


def _apply_event_assignments(
    rows: list[dict],
    assignments: dict[int, EventAssignment],
) -> list[dict]:
    """Keep only canonicals and content not assigned to an accepted event."""

    visible: list[dict] = []
    for row in rows:
        content_id = row.get("id")
        assignment = assignments.get(int(content_id)) if content_id is not None else None
        if assignment is None or assignment.is_canonical:
            visible.append(row)
    return visible


def _attach_event_normalization(
    items: list[dict],
    assignments: dict[int, EventAssignment],
    groups: dict[int, EventDisplayGroup],
) -> None:
    """Attach accepted event members to visible canonical cards."""
    for item in items:
        assignment = assignments.get(int(item["id"]))
        if assignment is None or not assignment.is_canonical:
            continue
        group = groups.get(assignment.event_group_id)
        if group is None:
            item["normalization"] = {
                "canonical_id": item["id"],
                "member_count": 0,
                "source_count": 1,
                "has_more": False,
                "members": [],
            }
            continue
        item["normalization"] = {
            "canonical_id": group.canonical_content_id,
            "member_count": group.member_count,
            "source_count": group.source_count,
            "has_more": group.member_count > len(group.members),
            "members": [
                {
                    "id": member.content_id,
                    "title": member.title,
                    "url": member.url,
                    "source_name": member.source_name,
                    "source_type": member.source_type,
                    "platform": member.platform,
                    "published_at": _serialize_event_datetime(member.published_at),
                    "crawled_at": _serialize_event_datetime(member.crawled_at),
                    "relation_type": member.relation_type,
                    "confidence": member.confidence,
                    "reason": member.reason,
                }
                for member in group.members
            ],
        }


def _serialize_event_datetime(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _pack_today_picks(
    items: list[dict],
    topic_map: dict,
    *,
    total: int,
    event_members_hidden: int = 0,
) -> dict:
    topic_ids = {item.get("topic_id") for item in items if item.get("topic_id")}
    visible_topics = [topic for topic in topic_map.values() if topic["id"] in topic_ids]
    return {
        "items": items,
        "total": total,
        "event_members_hidden": event_members_hidden,
        "topics": visible_topics,
        "page": 1,
        "page_size": len(items),
    }
