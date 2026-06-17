"""
七猫小说 API。
"""

from __future__ import annotations


from fastapi import APIRouter, Query, Depends, BackgroundTasks
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.qimao import QimaoBook
from app.models.user import User

router = APIRouter(prefix="/qimao", tags=["qimao"])


def _book_url(book_id: str) -> str:
    return f"https://www.qimao.com/shuku/{book_id}/"


@router.get("/rankings")
async def rankings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    channel: str = Query("boy", description="boy / girl"),
):
    """各榜单概览：每个榜单有多少本。"""
    rows = await db.execute(
        select(
            QimaoBook.channel,
            QimaoBook.rank_type,
            func.count(QimaoBook.id).label("count"),
        )
        .where(QimaoBook.channel == channel)
        .group_by(QimaoBook.channel, QimaoBook.rank_type)
    )
    rank_labels = {
        "hot": "大热榜",
        "new": "新书榜",
        "over": "完结榜",
        "collect": "收藏榜",
        "update": "更新榜",
    }
    result = {}
    for row in rows:
        result[row.rank_type] = {
            "label": rank_labels.get(row.rank_type, row.rank_type),
            "count": row.count,
            "channel": row.channel,
        }
    return {"channel": channel, "rankings": result}


@router.get("/categories")
async def categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    channel: str = Query(None, description="boy / girl，不传则返回全部"),
):
    """分类列表：从已有数据中提取去重的 category1_name。"""
    query = select(
        QimaoBook.category1_name,
        QimaoBook.channel,
        func.count(QimaoBook.id).label("book_count"),
    ).group_by(QimaoBook.category1_name, QimaoBook.channel)

    if channel:
        query = query.where(QimaoBook.channel == channel)

    rows = await db.execute(query)
    cats = []
    for row in rows:
        if row.category1_name:
            cats.append(
                {
                    "name": row.category1_name,
                    "channel": row.channel,
                    "book_count": row.book_count,
                }
            )
    return {"categories": cats, "total": len(cats)}


@router.get("/books")
async def list_books(
    channel: str = Query("boy", description="boy / girl"),
    rank_type: str = Query("hot", description="hot / new / over / collect / update"),
    category: str = Query(None, description="按 category1_name 过滤"),
    limit: int = Query(20, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """指定榜单的图书列表。"""
    query = (
        select(QimaoBook)
        .where(QimaoBook.channel == channel, QimaoBook.rank_type == rank_type)
        .order_by(QimaoBook.position)
    )
    if category:
        query = query.where(QimaoBook.category1_name == category)

    # Total count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.offset(offset).limit(limit)
    rows = await db.execute(query)
    books = rows.scalars().all()

    return {
        "channel": channel,
        "rank_type": rank_type,
        "total": total,
        "offset": offset,
        "limit": limit,
        "books": [
            {
                "book_id": b.book_id,
                "url": _book_url(b.book_id),
                "title": b.title,
                "author": b.author,
                "abstract": b.abstract,
                "category1_name": b.category1_name,
                "category2_name": b.category2_name,
                "thumb_uri": b.thumb_uri,
                "words_num": b.words_num,
                "collect_count": b.collect_count,
                "latest_chapter_title": b.latest_chapter_title,
                "update_time": b.update_time,
                "is_over": b.is_over,
                "is_new": b.is_new,
                "is_continue_top": b.is_continue_top,
                "index_change": b.index_change,
                "position": b.position,
                "crawled_at": b.crawled_at.isoformat() if b.crawled_at else None,
            }
            for b in books
        ],
    }


@router.post("/sync")
async def sync_qimao(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_admin_user),
):
    """后台触发七猫全量同步（耗时约 30s）。"""
    from app.scheduler import _sync_qimao

    background_tasks.add_task(_sync_qimao)
    return {"status": "started", "message": "七猫同步已在后台启动，预计 30s 内完成"}
