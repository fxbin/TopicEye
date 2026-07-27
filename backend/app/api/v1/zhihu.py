"""
知乎盐选专栏 API。
"""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.user import User
from app.repositories.zhihu_repo import ZhihuRepository

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
    """拼接存储用的 sort_type（如 "hottest__1512"）。"""
    return f"{sort_type}__{category_id}"


def _resolve_album_scope(
    category: str | None,
    subcategory: str | None,
    sort_type: str,
) -> tuple[str, str | None]:
    """根据业务层 category/subcategory 解析实际存储的 sort_type 与子分类标签。"""
    if category == "故事":
        if subcategory:
            cat_id = STORY_SUBCAT_IDS.get(subcategory)
            if cat_id:
                return _storage_sort_type(sort_type, cat_id), subcategory
            return sort_type, subcategory
        return _storage_sort_type(sort_type, STORY_CATEGORY_ID), STORY_ALL_LABEL
    return sort_type, subcategory


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
    repo = ZhihuRepository(db)
    db_sort_type, resolved_subcategory = _resolve_album_scope(category, subcategory, sort_type)
    subcategories = (resolved_subcategory,) if resolved_subcategory else ()

    albums = await repo.list_albums_with_filters(
        sort_type=db_sort_type,
        category=category,
        subcategories=subcategories,
        limit=limit,
        offset=offset,
    )
    count_sort_type = db_sort_type
    count_subcategories = subcategories

    if not albums and db_sort_type != sort_type:
        fallback_subcategories = (subcategory,) if subcategory else LEGACY_STORY_GROUPS.get(sort_type, ())
        albums = await repo.list_albums_with_filters(
            sort_type=sort_type,
            category=category,
            subcategories=fallback_subcategories,
            limit=limit,
            offset=offset,
        )
        if albums:
            count_sort_type = sort_type
            count_subcategories = fallback_subcategories

    total = await repo.count_albums_with_filters(
        sort_type=count_sort_type,
        category=category,
        subcategories=count_subcategories,
    )

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
    repo = ZhihuRepository(db)
    cats = await repo.list_categories_by_parent_id(parent_id)

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
