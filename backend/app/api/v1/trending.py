"""
趋势雷达 API — GET /api/v1/trending
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from pydantic import BaseModel, field_serializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.config import settings
from app.core.database import async_session, get_db
from app.models.trending import TrendingCategory, TrendingItem, TrendingSource
from app.services.trending_cache import (
    TRENDING_SOURCES_CACHE_KEY,
    CrossPlatformCacheParams,
    PersistentTopicsCacheParams,
    TrendingListCacheParams,
    get_cached_cross_platform,
    get_cached_persistent_topics,
    get_cached_trending_list,
    get_cached_trending_sources,
    invalidate_trending_cache,
    set_cached_cross_platform,
    set_cached_persistent_topics,
    set_cached_trending_list,
    set_cached_trending_sources,
)
from app.services.trending_pipeline import sync_all_trending, sync_trending_source
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/trending", tags=["trending"])
DEFAULT_TRENDING_LIST_LIMIT = 200
DEFAULT_TRENDING_MIN_RESONANCE = 2
DEFAULT_TRENDING_CROSS_LIMIT = 50
DEFAULT_TRENDING_MIN_DAYS = 2
DEFAULT_TRENDING_MIN_SOURCES = 1
DEFAULT_TRENDING_DAYS_BACK = 7


class TrendingItemOut(BaseModel):
    id: int
    source: str
    category: str
    rank: int
    title: str
    url: str
    hot_value: int
    hot_value_raw: str
    trend: str | None = None
    cover_url: str | None = None
    extra: dict | None = None

    model_config = {"from_attributes": True}

    @field_serializer("url")
    def serialize_url(self, value: str) -> str:
        return normalize_zhihu_url(value)


class TrendingSourceInfo(BaseModel):
    source: str
    category: str
    count: int
    last_synced: str | None = None


@router.get("", response_model=list[TrendingItemOut])
async def get_trending(
    category: str | None = Query(None, description="分类筛选: hot/tech/finance/entertainment/community"),
    source: str | None = Query(None, description="信源筛选: weibo/baidu/douyin/..."),
    exclude_sources: str | None = Query(
        None,
        description="排除的信源，逗号分隔（如 'heiyan,ishugui' 排除网文平台）",
    ),
    limit: int = Query(30, ge=1, le=500),
):
    """获取趋势雷达数据。支持按分类和信源筛选。"""
    exclude_list = [s.strip() for s in (exclude_sources or "").split(",") if s.strip()]
    cache_params = TrendingListCacheParams(
        category=category, source=source, limit=limit, exclude_sources=tuple(exclude_list),
    )
    cached = get_cached_trending_list(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Trending-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    async with async_session() as db:
        payload = await build_trending_list_payload(
            db,
            category=category,
            source=source,
            limit=limit,
            exclude_sources=exclude_list or None,
        )
    content = set_cached_trending_list(cache_params, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Trending-Cache": "MISS"},
    )


async def build_trending_list_payload(
    db: AsyncSession,
    *,
    category: str | None = None,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
    limit: int = 30,
) -> list[dict]:
    stmt = select(TrendingItem)

    if category:
        try:
            cat_enum = TrendingCategory(category)
            stmt = stmt.where(TrendingItem.category == cat_enum)
        except ValueError:
            pass
    if source:
        try:
            src_enum = TrendingSource(source)
            stmt = stmt.where(TrendingItem.source == src_enum)
        except ValueError:
            pass
    if exclude_sources:
        # Convert string source names to TrendingSource enums (silently skip unknowns)
        exclude_enums = []
        for s in exclude_sources:
            try:
                exclude_enums.append(TrendingSource(s))
            except ValueError:
                pass
        if exclude_enums:
            stmt = stmt.where(TrendingItem.source.notin_(exclude_enums))

    stmt = stmt.order_by(TrendingItem.source, TrendingItem.rank).limit(limit * 10)
    result = await db.execute(stmt)
    items = result.scalars().all()
    return [TrendingItemOut.model_validate(item).model_dump() for item in items]


@router.get("/sources", response_model=list[TrendingSourceInfo])
async def get_trending_sources():
    """获取所有趋势源及其条目数量和最后同步时间。"""
    cached = get_cached_trending_sources(ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Trending-Sources-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    async with async_session() as db:
        payload = await build_trending_sources_payload(db)
    content = set_cached_trending_sources(payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Trending-Sources-Cache": "MISS"},
    )


async def build_trending_sources_payload(db: AsyncSession) -> list[dict]:
    stmt = (
        select(
            TrendingItem.source,
            TrendingItem.category,
            func.count(TrendingItem.id).label("count"),
            func.max(TrendingItem.fetched_at).label("last_synced"),
        )
        .group_by(TrendingItem.source, TrendingItem.category)
        .order_by(TrendingItem.category, TrendingItem.source)
    )
    result = await db.execute(stmt)
    rows = result.all()
    payload = [
        TrendingSourceInfo(
            source=row[0],
            category=row[1],
            count=row[2],
            last_synced=row[3].isoformat() if row[3] else None,
        ).model_dump()
        for row in rows
    ]
    return payload


@router.post("/sync-all", dependencies=[Depends(get_current_admin_user)])
async def trigger_sync_all(
    db: AsyncSession = Depends(get_db),
):
    """手动触发所有趋势源同步。"""
    results = await sync_all_trending(db)
    invalidate_trending_cache()
    return results


@router.post("/sync/{source_name}", dependencies=[Depends(get_current_admin_user)])
async def trigger_sync(
    source_name: str,
    db: AsyncSession = Depends(get_db),
):
    """手动触发单个趋势源同步。"""
    result = await sync_trending_source(source_name, db)
    invalidate_trending_cache()
    return result


@router.get("/cross-platform")
async def get_cross_platform(
    min_resonance: int = Query(1, ge=1, le=10, description="最小共振平台数"),
    limit: int = Query(30, ge=1, le=100),
):
    """跨平台热点交叉发现。

    对所有趋势数据做标题聚类，找出在多平台同时出现的热点话题。
    resonance >= 3 为"高共振"，值得关注。
    """
    cache_params = CrossPlatformCacheParams(min_resonance=min_resonance, limit=limit)
    cached = get_cached_cross_platform(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Trending-Cross-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    async with async_session() as db:
        payload = await build_cross_platform_payload(db, min_resonance=min_resonance, limit=limit)
    content = set_cached_cross_platform(cache_params, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Trending-Cross-Cache": "MISS"},
    )


async def build_cross_platform_payload(db: AsyncSession, *, min_resonance: int, limit: int) -> dict:
    from app.services.trending_cross import cluster_trending_items

    stmt = select(TrendingItem).order_by(TrendingItem.source, TrendingItem.rank)
    result = await db.execute(stmt)
    items = result.scalars().all()

    item_dicts = [
        {
            "id": it.id,
            "source": it.source.name if hasattr(it.source, "name") else str(it.source),
            "category": it.category.name if hasattr(it.category, "name") else str(it.category),
            "rank": it.rank,
            "title": it.title,
            "url": normalize_zhihu_url(it.url),
            "hot_value": it.hot_value,
            "hot_value_raw": it.hot_value_raw,
            "trend": it.trend,
            "extra": it.extra,
        }
        for it in items
    ]

    clusters = cluster_trending_items(item_dicts)
    clusters = [c for c in clusters if c["resonance"] >= min_resonance]
    clusters = clusters[:limit]

    for c in clusters:
        for it in c.get("items", []):
            it.pop("_keywords", None)

    payload = {
        "total": len(clusters),
        "clusters": clusters,
    }
    return payload


# ── 历史快照 API ────────────────────────────────────────────────────────

@router.get("/snapshots/diff/{source}")
async def get_snapshot_diff_api(
    source: str,
    db: AsyncSession = Depends(get_db),
):
    """
    获取指定 source 的今日 vs 昨日快照对比。
    返回 rank 变化和新上榜/掉榜条目。
    """
    from app.services.trending_snapshot import get_snapshot_diff

    diff = await get_snapshot_diff(db, source)
    if diff is None:
        return {"source": source, "available": False, "changes": []}
    return {"source": source, "available": True, **diff}


@router.post("/snapshots/save", dependencies=[Depends(get_current_admin_user)])
async def manual_save_snapshots(
    db: AsyncSession = Depends(get_db),
):
    """手动触发保存所有趋势源快照（一般用于调试）。"""
    from app.services.trending_snapshot import save_all_snapshots

    results = await save_all_snapshots(db)
    await db.commit()
    invalidate_trending_cache()
    return {"saved": results}


@router.get("/persistent")
async def get_persistent_topics(
    min_days: int = Query(2, ge=1, le=7, description="最小连续在榜天数"),
    min_sources: int = Query(1, ge=1, le=10, description="最小涉及平台数"),
    days_back: int = Query(7, ge=1, le=30, description="分析最近N天"),
):
    """持续热度分析：找出连续多天在榜的话题。

    核心价值：
    - 单次榜单只能看到"现在什么火"
    - 持续在榜说明不是昙花一现，是真正值得追的话题
    - 跨平台共振 = 社会级话题，最值得写

    返回按天数+平台数排序的话题列表。
    """
    cache_params = PersistentTopicsCacheParams(
        min_days=min_days,
        min_sources=min_sources,
        days_back=days_back,
    )
    cached = get_cached_persistent_topics(cache_params, ttl_seconds=settings.READ_CACHE_TTL_SECONDS)
    if cached:
        content, age_seconds = cached
        return Response(
            content=content,
            media_type="application/json",
            headers={"X-Trending-Persistent-Cache": f"HIT; age={age_seconds:.3f}s"},
        )

    async with async_session() as db:
        payload = await build_persistent_topics_payload(
            db,
            min_days=min_days,
            min_sources=min_sources,
            days_back=days_back,
        )
    content = set_cached_persistent_topics(cache_params, payload)
    return Response(
        content=content,
        media_type="application/json",
        headers={"X-Trending-Persistent-Cache": "MISS"},
    )


async def build_persistent_topics_payload(
    db: AsyncSession,
    *,
    min_days: int,
    min_sources: int,
    days_back: int,
) -> dict:
    from app.services.trending_snapshot import analyze_persistent_topics

    topics = await analyze_persistent_topics(db, min_days, min_sources, days_back)
    return {
        "total": len(topics),
        "topics": topics,
    }


async def build_default_trending_cache_payloads(db: AsyncSession) -> dict[str, object]:
    list_params = TrendingListCacheParams(limit=DEFAULT_TRENDING_LIST_LIMIT)
    cross_params = CrossPlatformCacheParams(
        min_resonance=DEFAULT_TRENDING_MIN_RESONANCE,
        limit=DEFAULT_TRENDING_CROSS_LIMIT,
    )
    persistent_params = PersistentTopicsCacheParams(
        min_days=DEFAULT_TRENDING_MIN_DAYS,
        min_sources=DEFAULT_TRENDING_MIN_SOURCES,
        days_back=DEFAULT_TRENDING_DAYS_BACK,
    )
    return {
        list_params.key: await build_trending_list_payload(db, limit=DEFAULT_TRENDING_LIST_LIMIT),
        TRENDING_SOURCES_CACHE_KEY: await build_trending_sources_payload(db),
        cross_params.key: await build_cross_platform_payload(
            db,
            min_resonance=DEFAULT_TRENDING_MIN_RESONANCE,
            limit=DEFAULT_TRENDING_CROSS_LIMIT,
        ),
        persistent_params.key: await build_persistent_topics_payload(
            db,
            min_days=DEFAULT_TRENDING_MIN_DAYS,
            min_sources=DEFAULT_TRENDING_MIN_SOURCES,
            days_back=DEFAULT_TRENDING_DAYS_BACK,
        ),
    }


# ── 角度推荐 API ────────────────────────────────────────────────────────

class AngleRecommendOut(BaseModel):
    common_angles: list[str]
    contrast_angles: list[dict[str, str]]
    angle_note: str


@router.get("/angles", response_model=AngleRecommendOut, dependencies=[Depends(get_current_user)])
async def get_topic_angles(
    topic: str = Query(..., description="话题标题"),
    db: AsyncSession = Depends(get_db),
):
    """为指定话题生成创作角度推荐。

    基于卡兹克方法论：
    - 大众角度（第一直觉想到的不能写）
    - 反差角度（陌生化，情理之中预料之外）
    """
    from app.services.angle_recommend import generate_angles_for_topic

    # 从 DB 找到相关趋势条目，拼出各平台标题
    # 转义 LIKE 通配符，防止用户输入 %/_ 泄露非预期数据
    safe_topic = topic[:8].replace('%', '\\%').replace('_', '\\_')
    stmt = (
        select(TrendingItem)
        .where(TrendingItem.title.like(f"%{safe_topic}%"))
        .order_by(TrendingItem.rank)
        .limit(8)
    )
    result = await db.execute(stmt)
    items = result.scalars().all()

    if not items:
        return {"common_angles": [], "contrast_angles": [], "angle_note": "未找到相关话题数据"}

    platform_titles = [it.title for it in items]

    # 取第一个作为代表
    rep_item = items[0]
    keywords: list[str] = []
    if rep_item.extra and isinstance(rep_item.extra, dict):
        keywords = rep_item.extra.get("keywords", [])

    angles = await generate_angles_for_topic(
        topic=topic,
        keywords=keywords,
        platform_titles=platform_titles,
    )
    return angles
