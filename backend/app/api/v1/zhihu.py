"""
知乎盐选专栏 API。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.zhihu import ZhihuAlbum, ZhihuCategory
from app.models.user import User

router = APIRouter(prefix="/zhihu", tags=["知乎"])

STORY_CATEGORY_ID = "1512"
STORY_ALL_LABEL = "故事全部"
STORY_SUBCAT_IDS = {
    "爱情": "1513",
    "科幻": "1514",
    "历史": "1515",
    "漫画": "1516",
    "脑洞": "1517",
    "奇闻": "1518",
    "亲历": "1519",
    "校园": "1520",
    "悬疑": "1521",
}
LEGACY_STORY_GROUPS = {
    "hottest": ("故事全部", "故事", "全部", "热门"),
    "newest": ("故事全部", "故事", "全部", "最新"),
    "monthly_hottest": ("故事全部", "故事", "全部", "月热"),
}


def _storage_sort_type(sort_type: str, category_id: str) -> str:
    return f"{sort_type}__{category_id}"


def _resolve_album_scope(
    category: str | None,
    subcategory: str | None,
    sort_type: str,
) -> tuple[str, str | None]:
    if category == "故事":
        if subcategory:
            cat_id = STORY_SUBCAT_IDS.get(subcategory)
            if cat_id:
                return _storage_sort_type(sort_type, cat_id), subcategory
            return sort_type, subcategory
        return _storage_sort_type(sort_type, STORY_CATEGORY_ID), STORY_ALL_LABEL
    return sort_type, subcategory


def _apply_album_filters(query, sort_type: str, category: str | None, subcategories: tuple[str, ...]):
    query = query.where(ZhihuAlbum.sort_type == sort_type)
    if category:
        query = query.where(ZhihuAlbum.category1_name == category)
    if len(subcategories) == 1:
        query = query.where(ZhihuAlbum.category2_name == subcategories[0])
    elif subcategories:
        query = query.where(ZhihuAlbum.category2_name.in_(subcategories))
    return query


@router.get("/albums")
async def list_albums(
    category: str | None = Query(None, description="一级分类名"),
    subcategory: str | None = Query(None, description="二级分类名（如 爱情、科幻）"),
    sort_type: str = Query("hottest", description="排序类型"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """知乎盐选专辑列表（支持分类+子分类+排序过滤）。"""
    db_sort_type, resolved_subcategory = _resolve_album_scope(category, subcategory, sort_type)
    subcategories = (resolved_subcategory,) if resolved_subcategory else ()

    query = _apply_album_filters(select(ZhihuAlbum), db_sort_type, category, subcategories)
    query = query.order_by(ZhihuAlbum.position.asc(), ZhihuAlbum.updated_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    albums = result.scalars().all()
    count_sort_type = db_sort_type
    count_subcategories = subcategories

    if not albums and db_sort_type != sort_type:
        fallback_subcategories = (subcategory,) if subcategory else LEGACY_STORY_GROUPS.get(sort_type, ())
        fallback_q = _apply_album_filters(select(ZhihuAlbum), sort_type, category, fallback_subcategories)
        fallback_q = (
            fallback_q.order_by(ZhihuAlbum.position.asc(), ZhihuAlbum.updated_at.desc()).limit(limit).offset(offset)
        )
        fallback_result = await db.execute(fallback_q)
        albums = fallback_result.scalars().all()
        if albums:
            count_sort_type = sort_type
            count_subcategories = fallback_subcategories

    count_q = _apply_album_filters(
        select(func.count()).select_from(ZhihuAlbum), count_sort_type, category, count_subcategories
    )
    count_result = await db.execute(count_q)
    total = count_result.scalar() or 0

    return {
        "sort_type": sort_type,
        "category": category or "",
        "subcategory": resolved_subcategory or "",
        "count": len(albums),
        "total": total,
        "offset": offset,
        "albums": [
            {
                "business_id": a.business_id,
                "title": a.title,
                "author": a.author,
                "author_desc": a.author_desc,
                "abstract": a.abstract,
                "thumb_url": a.thumb_url,
                "chapter_text": a.chapter_text,
                "price_yuan": a.price_yuan,
                "price": a.price,
                "is_exclusive": a.is_exclusive,
                "is_svip": a.is_svip,
                "online_time_text": a.online_time_text,
                "tag": a.tag,
                "category1_name": a.category1_name,
                "category2_name": a.category2_name,
                "position": a.position,
                "rank_pos_diff": a.rank_pos_diff,
                "sort_type": sort_type,
                "url": a.url,
            }
            for a in albums
        ],
    }


@router.get("/categories")
async def list_categories(
    parent_id: str | None = Query(None, description="父分类 ID，null 表示一级分类"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """知乎盐选分类列表。"""
    if parent_id:
        query = select(ZhihuCategory).where(ZhihuCategory.parent_id == parent_id).order_by(ZhihuCategory.sort)
    else:
        query = select(ZhihuCategory).where(ZhihuCategory.parent_id == None).order_by(ZhihuCategory.sort)

    result = await db.execute(query)
    cats = result.scalars().all()

    return {
        "count": len(cats),
        "categories": [
            {
                "zhihu_id": c.zhihu_id,
                "name": c.name,
                "name_en": c.name_en,
                "level": c.level,
                "parent_id": c.parent_id,
                "sort": c.sort,
                "artwork": c.artwork,
            }
            for c in cats
        ],
    }


@router.post("/sync")
async def sync_zhihu(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_admin_user),
):
    """触发知乎全量同步（后台运行）。"""
    from app.scheduler import _sync_zhihu

    background_tasks.add_task(_sync_zhihu)
    return {"status": "syncing", "message": "知乎榜单后台同步已启动"}
