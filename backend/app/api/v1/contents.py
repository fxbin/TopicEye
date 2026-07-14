"""Content API endpoints — delegates all DB work to repositories."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user, get_optional_current_user
from app.core.config import settings
from app.core.database import async_session, database_profile, get_db
from app.core.sqlite_retry import is_sqlite_locked, retry_sqlite_locked
from app.models.content import ContentItem
from app.models.favorite import FavoriteTargetType
from app.models.user import User
from app.repositories.analysis_repo import AnalysisRepository
from app.repositories.content_repo import ContentRepo
from app.repositories.favorite_repo import FavoriteRepo
from app.schemas.analysis import AiAnalysisResponse
from app.schemas.content import ContentListResponse, ContentResponse
from app.services.content_list_cache import (
    ContentListCacheParams,
    get_cached_content_list,
    set_cached_content_list,
)
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.content_serialization import content_with_latest_analysis, latest_analysis_from_item
from app.services.favorite_cache import invalidate_favorite_cache
from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json
from app.services.scoring_flow import (
    DEFAULT_SCORING_FLOW_HOURS,
    DEFAULT_SCORING_FLOW_LIMIT,
    build_scoring_flow_payload,
    get_cached_scoring_flow_json,
)
from app.services.today_picks_cache import TodayPicksCacheParams, get_cached_today_picks, set_cached_today_picks

router = APIRouter(prefix="/contents", tags=["contents"])

# Large batch size for scoring — enough for diversity penalty to work well
_SCORING_BATCH_SIZE = 500
_TREND_SOURCE_TYPES = {"DouyinHot"}

logger = logging.getLogger(__name__)


class _LowLatencyBusyTimeout:
    """临时调低 SQLite busy_timeout（批量写时快速返回 503），退出时还原。

    上下文管理器避免重复样板：三个 favorite 端点共用同一套逻辑。
    非 SQLite 后端为 no-op。
    """

    def __init__(self, db: AsyncSession):
        self._db = db
        self._active = False

    async def __aenter__(self) -> _LowLatencyBusyTimeout:
        if database_profile.is_sqlite:
            try:
                await self._db.execute(text(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_BATCH_MS}"))
                self._active = True
            except Exception:
                await self._db.rollback()
        return self

    async def __aexit__(self, *exc_info) -> None:
        if self._active:
            try:
                await self._db.execute(text(f"PRAGMA busy_timeout={settings.SQLITE_BUSY_TIMEOUT_MS}"))
            except Exception:
                await self._db.rollback()
            self._active = False


def _is_admin(user: User | None) -> bool:
    return bool(user and user.role == "admin")


def _require_admin_view(admin_view: bool, user: User | None) -> None:
    if not admin_view:
        return
    if user is None:
        raise HTTPException(status_code=401, detail="Missing authorization header")
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Admin privileges required")


def _empty_list_response(page: int, page_size: int) -> dict:
    return {"items": [], "total": 0, "page": page, "page_size": page_size}


async def _score_content_page(
    db: AsyncSession,
    *,
    filters: dict,
    ignored_ids: list[int],
    time_cutoff: datetime | None,
    exclude_source_types: set[str] | None,
    page: int,
    page_size: int,
    score_fn,
    sort_order: str = "desc",
    visible_user_id: int | None = None,
) -> dict:
    from app.services.scoring_inputs import build_scoring_inputs

    scored_items, total = await ContentRepo(db).list_for_scoring(
        filters=filters,
        exclude_ids=ignored_ids,
        exclude_source_types=exclude_source_types,
        time_cutoff=time_cutoff,
        limit=_SCORING_BATCH_SIZE,
        visible_user_id=visible_user_id,
    )
    if not scored_items:
        return _empty_list_response(page, page_size)

    scoring_inputs, item_map, _ = await build_scoring_inputs(db, scored_items)
    if not scoring_inputs:
        return _empty_list_response(page, page_size)

    scored = sorted(
        score_fn(scoring_inputs),
        key=lambda pair: pair[0].final_score,
        reverse=(sort_order == "desc"),
    )
    page_offset = (page - 1) * page_size
    page_items = scored[page_offset : page_offset + page_size]
    result_items = [
        _with_scoring_breakdown(item_map, breakdown, scoring_input) for breakdown, scoring_input in page_items
    ]
    result_items = [item for item in result_items if item]

    return {
        "items": result_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _with_scoring_breakdown(item_map: dict, breakdown, scoring_input) -> dict | None:
    item = item_map.get(scoring_input.content_id)
    if not item:
        return None

    data = content_with_latest_analysis(item)
    if data.get("analysis"):
        data["analysis"]["adjusted_curation_score"] = breakdown.final_score
        data["analysis"]["score_breakdown"] = breakdown.to_dict()
    return data


@router.get("")
async def list_contents(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    source_type: str | None = None,
    platform: str | None = None,
    status: str | None = None,
    category: str | None = None,
    keyword: str | None = None,
    source_id: int | None = None,
    q: str | None = Query(None, description="全文搜索（跨 title + summary + raw_content 的 OR 匹配）"),
    include_trend_sources: bool = Query(False, description="Include榜单/趋势源 such as DouyinHot"),
    hours: int | None = Query(None, description="Time range in hours, e.g. 24, 48, 168"),
    sort_by: str = Query(
        "created_at", pattern=r"^(created_at|published_at|crawled_at|curation_score|low_follower_viral)$"
    ),
    sort_order: str = Query("desc", pattern=r"^(asc|desc)$"),
    admin_view: bool = Query(False, description="Return management fields; admin only"),
    current_user: User | None = Depends(get_optional_current_user),
):
    from datetime import timedelta

    from app.repositories.ignored_repo import IgnoredRepo

    _require_admin_view(admin_view, current_user)
    include_raw_content = _is_admin(current_user)

    cache_params = ContentListCacheParams(
        page=page,
        page_size=page_size,
        source_type=source_type,
        platform=platform,
        status=status,
        category=category,
        keyword=keyword,
        source_id=source_id,
        include_trend_sources=include_trend_sources,
        hours=hours,
        sort_by=sort_by,
        sort_order=sort_order,
        user_id=current_user.id if current_user is not None else None,
    )
    if cache_params.cacheable and not include_raw_content:
        cached = get_cached_content_list(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
        if cached:
            content, age_seconds = cached
            return Response(
                content=content,
                media_type="application/json",
                headers={"X-Content-List-Cache": f"HIT; age={age_seconds:.3f}s"},
            )

    async with async_session() as db:
        filters = {
            k: v
            for k, v in {
                "source_type": source_type,
                "platform": platform,
                "status": status,
                "category": category,
                "source_id": source_id,
                "title": f"%{keyword}%" if keyword else None,
            }.items()
            if v is not None
        }

        time_cutoff = None
        if hours:
            time_cutoff = datetime.now(UTC) - timedelta(hours=hours)

        ignored_ids = await IgnoredRepo(db).list_ignored_ids()
        exclude_source_types = None if include_trend_sources else _TREND_SOURCE_TYPES

        # ── Curation-score ranking path ────────────────────────────────────
        if sort_by == "curation_score":
            from app.services.scoring_engine import score_items

            return await _score_content_page(
                db,
                filters=filters,
                ignored_ids=ignored_ids,
                time_cutoff=time_cutoff,
                exclude_source_types=exclude_source_types,
                page=page,
                page_size=page_size,
                score_fn=score_items,
                sort_order=sort_order,
                visible_user_id=current_user.id if current_user is not None else None,
            )

        # ── Low-follower viral discovery path ────────────────────────────────
        if sort_by == "low_follower_viral":
            # 优先走 DuckDB（消除 500 行 Python 批处理）；不可用时 fallback 到原路径
            try:
                import asyncio

                from app.services.duckdb_service import get_analytics

                analytics = get_analytics()
                if analytics.available:
                    lfv_hours = hours or 48
                    offset = (page - 1) * page_size
                    # DuckDB 是同步的，推到 worker thread 避免阻塞事件循环
                    lfv_items, lfv_total = await asyncio.to_thread(
                        analytics.query_low_follower_viral,
                        hours=lfv_hours,
                        category=category,
                        limit=page_size,
                        offset=offset,
                    )
                    result_items = []
                    for lfv in lfv_items:
                        raw = lfv["raw_item"]
                        analysis_data = {
                            "adjusted_curation_score": lfv["lfv_final"],
                            "score_breakdown": {
                                "final_score": lfv["lfv_final"],
                                "base_score": lfv["content_score"],
                                "source_bonus": lfv["obscure_factor"],
                                "time_decay": lfv["time_decay"],
                                "dimension_scores": {
                                    "viral_score": raw.get("viral_score", 0),
                                    "creator_score": raw.get("creator_score", 0),
                                    "quality_score": raw.get("quality_score", 0),
                                    "source_weight": raw.get("source_weight") or 0,
                                    "obscure_factor": lfv["obscure_factor"],
                                    "freshness_boost": lfv["freshness_boost"],
                                },
                            },
                            "curation_score": raw.get("curation_score"),
                            "quality_score": raw.get("quality_score"),
                            "freshness_score": raw.get("freshness_score"),
                            "creator_score": raw.get("creator_score"),
                            "viral_score": raw.get("viral_score"),
                            "risk_score": raw.get("risk_score"),
                        }
                        result_items.append({
                            "id": raw["id"],
                            "title": raw["title"],
                            "url": raw["url"],
                            "source_id": raw["source_id"],
                            "source_name": raw["source_name"],
                            "source_type": raw["source_type"],
                            "platform": raw["platform"],
                            "author": raw["author"],
                            "published_at": raw.get("published_at"),
                            "crawled_at": raw.get("crawled_at"),
                            "content_hash": raw.get("content_hash"),
                            "summary": raw.get("summary"),
                            "cover_url": raw.get("cover_url"),
                            "category": raw.get("category"),
                            "tags": raw.get("tags"),
                            "status": raw.get("status"),
                            "topic_id": raw.get("topic_id"),
                            "duplicate_of": raw.get("duplicate_of"),
                            "similarity_score": raw.get("similarity_score"),
                            "created_at": raw.get("created_at"),
                            "analysis": analysis_data,
                        })

                    payload = {"items": result_items, "total": lfv_total, "page": page, "page_size": page_size}
                    content = set_cached_content_list(cache_params, payload) if cache_params.cacheable and not include_raw_content else None
                    return Response(
                        content=content or json.dumps(payload, default=str),
                        media_type="application/json",
                        headers={"X-Content-List-Cache": "MISS (DuckDB-LFV)"},
                    )
            except Exception:
                logger.warning("DuckDB LFV path failed, falling back to Python scoring", exc_info=True)

            from app.services.scoring_engine import score_low_follower_viral

            return await _score_content_page(
                db,
                filters=filters,
                ignored_ids=ignored_ids,
                time_cutoff=time_cutoff,
                exclude_source_types=exclude_source_types,
                page=page,
                page_size=page_size,
                score_fn=score_low_follower_viral,
                visible_user_id=current_user.id if current_user is not None else None,
            )

        # ── Standard SQL sort path ─────────────────────────────────────────
        repo = ContentRepo(db)
        items, total = await repo.list_paginated_with_analyses(
            page=page,
            page_size=page_size,
            filters=filters or None,
            sort_by=sort_by,
            sort_order=sort_order,
            exclude_ids=ignored_ids,
            exclude_source_types=exclude_source_types,
            time_cutoff=time_cutoff,
            visible_user_id=current_user.id if current_user is not None else None,
            search_query=q,
        )
        payload = {
            "items": [content_with_latest_analysis(i, include_raw_content=include_raw_content) for i in items],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
        if cache_params.cacheable and not include_raw_content:
            content = set_cached_content_list(cache_params, payload)
            return Response(
                content=content,
                media_type="application/json",
                headers={"X-Content-List-Cache": "MISS"},
            )
        return payload


@router.get("/today-picks")
async def today_picks(
    category: str | None = Query(None, description="Filter by category"),
    time_range: str | None = Query(None, description="Time range: 24h, 48h, 7d"),
    limit: int | None = Query(None, ge=1, le=200, description="Limit returned items while preserving total"),
):
    """Top picks — curation_score adjusted by source weight, threshold 60."""
    from app.services.today_picks import build_today_picks

    params = TodayPicksCacheParams(
        category=category,
        hours={"24h": 24, "7d": 168}.get(time_range or "", 48),
        limit=limit,
    )
    cached = get_cached_today_picks(params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={
                "X-Analytics-Backend": "duckdb",
                "X-Today-Picks-Cache": f"HIT; age={age_seconds:.3f}s",
            },
        )

    try:
        async with async_session() as db:
            payload = await build_today_picks(db, category=category, hours=params.hours, limit=params.limit)
            content = set_cached_today_picks(params, payload)
            return Response(
                content=content,
                media_type="application/json",
                headers={
                    "X-Analytics-Backend": "duckdb",
                    "X-Today-Picks-Cache": "MISS",
                },
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="DuckDB analytical layer unavailable") from exc



@router.get("/today-count")
async def today_count():
    """返回滚动 48 小时的内容总数 + 当日精选数。

    用于侧边栏 badge 计数。口径与首页「今日选题」和「当日精选」页面一致:
    - today_content: 滚动 48h 内 analyzed 且非重复的内容数 (同首页默认 48h)
    - today_picks: 当日精选数 (同 /contents/today-picks 的 total)
    """
    from datetime import timedelta

    from app.services.json_cache import get_cached_json, set_cached_json

    cache_key = "today_count:v2"
    cached = get_cached_json(cache_key, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        return Response(
            content=cached[0],
            media_type="application/json",
            headers={"X-Today-Count-Cache": f"HIT; age={cached[1]:.3f}s"},
        )

    result = {"today_content": 0, "today_picks": 0}
    cutoff = datetime.now(UTC) - timedelta(hours=48)

    # 滚动 24h 内容数:与 /contents?hours=24 同口径
    try:
        async with async_session() as db:
            r = await db.execute(
                select(ContentItem.id).where(
                    ContentItem.status == "analyzed",
                    ContentItem.crawled_at >= cutoff,
                    ContentItem.duplicate_of.is_(None),
                )
            )
            result["today_content"] = len(r.all())
    except Exception:
        logger.warning("today_count content query failed", exc_info=True)

    # 当日精选数:复用 /today-picks 的 build_today_picks,拿到同样的 total
    try:
        from app.services.today_picks import build_today_picks

        async with async_session() as db:
            payload = await build_today_picks(db, category=None, hours=48)
            result["today_picks"] = payload.get("total", 0)
    except Exception:
        logger.warning("today_count picks query failed", exc_info=True)

    payload = json.dumps(result, default=str)
    set_cached_json(cache_key, payload)
    return Response(
        content=payload,
        media_type="application/json",
        headers={"X-Today-Count-Cache": "MISS"},
    )


@router.get("/scoring-flow")
async def scoring_flow(
    hours: int | None = Query(None, ge=1, le=720),
    limit: int | None = Query(None, ge=20, le=500),
    current_user: User = Depends(get_current_user),
):
    """Return a read-only explanation payload for the content scoring funnel."""
    hours = hours or DEFAULT_SCORING_FLOW_HOURS
    limit = limit or DEFAULT_SCORING_FLOW_LIMIT

    cached = get_cached_scoring_flow_json(hours=hours, limit=limit, visible_user_id=current_user.id)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Scoring-Flow-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    try:
        async with async_session() as db:
            payload = await build_scoring_flow_payload(
                db,
                hours=hours,
                limit=limit,
                visible_user_id=current_user.id,
            )
            return Response(
                content=json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
                media_type="application/json",
                headers={"X-Scoring-Flow-Cache": "MISS"},
            )
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Scoring flow unavailable") from exc


@router.get("/favorites/list", response_model=ContentListResponse)
async def list_favorites(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    cache_key = f"contents:favorites:list:{current_user.id}:{page}:{page_size}"
    cached = get_cached_json(cache_key, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Content-Favorites-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    favorites, total = await FavoriteRepo(db, current_user.id).list_paginated(
        page=page,
        page_size=page_size,
        target_type=FavoriteTargetType.CONTENT,
    )
    content_ids = [item.target_id for item in favorites if item.target_id is not None]
    if content_ids:
        result = await db.execute(select(ContentItem).where(ContentItem.id.in_(content_ids)))
        by_id = {item.id: item for item in result.scalars().all()}
        items = [by_id[content_id] for content_id in content_ids if content_id in by_id]
    else:
        items = []
    payload = {
        "items": [content_with_latest_analysis(i) for i in items],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    content = set_cached_json(cache_key, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Content-Favorites-Cache": "MISS"},
    )


@router.get("/{content_id}/enrich")
async def get_enrichment(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get or trigger Round-2 enrichment for a content item."""
    from app.services.enricher import enrich_content

    repo = AnalysisRepository(db)
    analysis = await repo.get_by_content_id(content_id)
    if not analysis:
        raise HTTPException(404, "No analysis found for this content")
    if analysis.enrichment_status == "completed" and analysis.enrichment:
        return {"content_id": content_id, "status": "completed", "enrichment": analysis.enrichment}
    if analysis.enrichment_status == "processing":
        return {"content_id": content_id, "status": "processing", "enrichment": None}

    claimed_analysis = await repo.claim_enrichment_for_content(content_id)
    await db.commit()
    if not claimed_analysis:
        return {"content_id": content_id, "status": "processing", "enrichment": None}

    try:
        data = await enrich_content(content_id, db)
        claimed_analysis.enrichment, claimed_analysis.enrichment_status = data, "completed"
        await db.flush()
        invalidate_content_read_caches()
        return {"content_id": content_id, "status": "completed", "enrichment": data}
    except Exception as e:
        claimed_analysis.enrichment_status = "error"
        await db.commit()
        invalidate_content_read_caches()
        raise HTTPException(500, f"Enrichment failed: {e}") from e


@router.post("/enrich-batch")
async def enrich_top_items(
    min_score: float = Query(70.0, ge=0, le=100),
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Batch-enrich top curated items (scheduler-friendly)."""
    from app.services.enricher import enrich_batch

    ids = await AnalysisRepository(db).claim_pending_enrichment_ids(min_score, limit)
    await db.commit()
    if not ids:
        return {"message": "No items need enrichment", "processed": []}
    return {"processed": await enrich_batch(ids, db)}


@router.get("/{content_id}")
async def get_content(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
):
    content = await ContentRepo(db).get_detail(
        content_id,
        visible_user_id=current_user.id if current_user is not None else None,
    )
    if not content:
        raise HTTPException(404, "Content not found")
    d = ContentResponse.model_validate(content).model_dump()
    if not _is_admin(current_user):
        d["raw_content"] = None
    a = latest_analysis_from_item(content)
    if a:
        a_dict = AiAnalysisResponse.model_validate(a).model_dump()
        # Include curation detail fields
        a_dict["info_density"] = a.info_density
        a_dict["actionability"] = a.actionability
        a_dict["source_weight"] = a.source_weight
        a_dict["curation_score"] = a.curation_score
        a_dict["recommendation"] = a.recommendation
        # Include enrichment if available
        if a.enrichment_status == "completed" and a.enrichment:
            a_dict["enrichment"] = a.enrichment
            a_dict["enrichment_status"] = a.enrichment_status
        d["analysis"] = a_dict
    if content.metrics:
        from app.schemas.content import ContentMetricsResponse

        d["metrics"] = [ContentMetricsResponse.model_validate(m).model_dump() for m in content.metrics]
    return d


@router.post("/{content_id}/favorite")
async def toggle_favorite(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Toggle favorite status for a content item."""
    result = await db.execute(select(ContentItem.id).where(ContentItem.id == content_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, "Content not found")

    favorite_repo = FavoriteRepo(db, current_user.id)
    target_key = favorite_repo.make_target_key(FavoriteTargetType.CONTENT, target_id=content_id)
    current = await favorite_repo.get_by_target(FavoriteTargetType.CONTENT, target_key)
    next_value = current is None

    async def _write() -> int | None:
        if next_value:
            favorite = await favorite_repo.create_from_content(content_id)
            favorite_id = favorite.id
        else:
            await favorite_repo.remove_by_content(content_id)
            favorite_id = None
        invalidate_favorite_cache()
        invalidate_content_read_caches()
        invalidate_json_cache("contents:favorites:")
        await db.flush()
        return favorite_id

    try:
        async with _LowLatencyBusyTimeout(db):
            favorite_id = await retry_sqlite_locked(_write, attempts=3, base_delay=0.1, on_retry=db.rollback)
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail="数据库繁忙，请稍后重试") from exc
        raise
    return {"is_favorited": next_value, "favorite_id": favorite_id}


@router.post("/{content_id}/ignore")
async def ignore_content(
    content_id: int,
    reason: str = Query("not_interested", description="Ignore reason: not_interested, seen, irrelevant"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a content item as ignored (won't appear in feeds)."""
    from app.repositories.ignored_repo import IgnoredRepo

    content = await ContentRepo(db).get_by_id(content_id)
    if not content:
        raise HTTPException(404, "Content not found")

    async def _write():
        ignored_item = await IgnoredRepo(db).ignore(content_id, reason=reason)
        await db.flush()
        return ignored_item

    try:
        async with _LowLatencyBusyTimeout(db):
            ignored = await retry_sqlite_locked(_write, attempts=3, base_delay=0.1, on_retry=db.rollback)
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail="数据库繁忙，请稍后重试") from exc
        raise
    invalidate_content_read_caches()
    return {"content_id": content_id, "ignored": True, "reason": ignored.reason}


@router.delete("/{content_id}/ignore")
async def unignore_content(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove ignore flag from a content item."""
    from app.repositories.ignored_repo import IgnoredRepo

    async def _write():
        return await IgnoredRepo(db).unignore(content_id)

    try:
        async with _LowLatencyBusyTimeout(db):
            removed = await retry_sqlite_locked(_write, attempts=3, base_delay=0.1, on_retry=db.rollback)
    except OperationalError as exc:
        await db.rollback()
        if is_sqlite_locked(exc):
            raise HTTPException(status_code=503, detail="数据库繁忙，请稍后重试") from exc
        raise
    invalidate_content_read_caches()
    return {"content_id": content_id, "ignored": False, "removed": removed}
