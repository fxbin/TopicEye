"""
番茄小说榜单 API。
提供分类列表、四大榜单、各分类书单。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.fanqie import FanqieCategory, FanqieBook
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/fanqie", tags=["番茄小说"])


def _book_url(book_id: str) -> str:
    return f"https://fanqienovel.com/page/{book_id}"


# ── Pydantic 模型 ──────────────────────────────────────────────


class BookItem(BaseModel):
    book_id: str
    url: str
    book_name: str
    author: str
    abstract: Optional[str]
    category_id: str
    category_name: Optional[str]
    thumb_uri: Optional[str]
    read_count: Optional[str]
    word_number: Optional[str]
    last_chapter_title: Optional[str]
    current_pos: int
    male_reading_pos: Optional[int]
    male_new_pos: Optional[int]
    female_reading_pos: Optional[int]
    female_new_pos: Optional[int]
    rank_pos_diff: Optional[int] = None  # 排名变化（正=上升，负=下降，null=新上榜）

    model_config = {"from_attributes": True}


class CategoryItem(BaseModel):
    fanqie_id: str
    name: str
    group: str
    display_order: int

    model_config = {"from_attributes": True}


class RankingItem(BaseModel):
    type: str
    label: str
    books: list[BookItem]


# ── API 端点 ───────────────────────────────────────────────────


@router.get("/categories")
async def list_categories(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> list[dict]:
    """返回所有番茄分类（按 group 和 display_order 排序）。"""
    result = await db.execute(
        select(FanqieCategory).order_by(
            FanqieCategory.group,
            FanqieCategory.display_order,
        )
    )
    cats = result.scalars().all()
    return [{"fanqie_id": c.fanqie_id, "name": c.name, "group": c.group} for c in cats]


@router.get("/rankings")
async def list_rankings(
    type: Optional[str] = Query(None, description="male_reading/male_new/female_reading/female_new"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> dict:
    """
    返回四大榜单（或指定某榜单）。
    type 可选：male_reading / male_new / female_reading / female_new
    """
    types = [type] if type else ["male_reading", "male_new", "female_reading", "female_new"]
    labels = {
        "male_reading": "男频阅读榜",
        "male_new": "男频新书榜",
        "female_reading": "女频阅读榜",
        "female_new": "女频新书榜",
    }

    out = {}
    for rt in types:
        result = await db.execute(
            select(FanqieBook).where(FanqieBook.rank_type == rt).order_by(FanqieBook.current_pos).limit(100)
        )
        books = result.scalars().all()
        out[rt] = {
            "label": labels.get(rt, rt),
            "count": len(books),
            "books": [
                {
                    "book_id": b.book_id,
                    "url": _book_url(b.book_id),
                    "book_name": b.book_name,
                    "author": b.author,
                    "abstract": b.abstract,
                    "thumb_uri": b.thumb_uri,
                    "read_count": b.read_count,
                    "word_number": b.word_number,
                    "last_chapter_title": b.last_chapter_title,
                    "current_pos": b.current_pos,
                    "rank_pos_diff": b.rank_pos_diff,
                }
                for b in books
            ],
        }
    return out


@router.get("/category/{fanqie_id}/books")
async def category_books(
    fanqie_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    rank_type: Optional[str] = Query(None, description="new / reading"),
    limit: int = Query(20, le=100),
) -> dict:
    """
    返回指定分类下的图书。
    rank_type: "new" 新书榜 / "reading" 阅读榜，默认返回新书榜。
    通过 pos 字段过滤（同一本书可能在多个榜单上有排名）。
    """
    # 先查分类信息确定 gender
    cat_result = await db.execute(select(FanqieCategory).where(FanqieCategory.fanqie_id == fanqie_id))
    cat = cat_result.scalar_one_or_none()
    gender = cat.group if cat else "male"

    # 选择对应的 pos 字段
    if rank_type == "reading":
        pos_field = "male_reading_pos" if gender == "male" else "female_reading_pos"
    else:
        pos_field = "male_new_pos" if gender == "male" else "female_new_pos"

    # 查询：只返回在该榜单有排名的书
    query = (
        select(FanqieBook)
        .where(
            FanqieBook.category_id == fanqie_id,
            getattr(FanqieBook, pos_field) != None,  # type: ignore
        )
        .order_by(getattr(FanqieBook, pos_field))
        .limit(limit)
    )

    result = await db.execute(query)
    books = result.scalars().all()

    return {
        "fanqie_id": fanqie_id,
        "rank_type": rank_type,
        "gender": gender,
        "count": len(books),
        "books": [
            {
                "book_id": b.book_id,
                "url": _book_url(b.book_id),
                "book_name": b.book_name,
                "author": b.author,
                "abstract": b.abstract,
                "thumb_uri": b.thumb_uri,
                "read_count": b.read_count,
                "word_number": b.word_number,
                "last_chapter_title": b.last_chapter_title,
                "position": getattr(b, pos_field),
                "rank_type": rank_type,
                "rank_pos_diff": b.rank_pos_diff,
            }
            for b in books
        ],
    }


@router.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_admin_user),
):
    """后台触发番茄全量同步。"""
    from app.scheduler import _sync_fanqie

    background_tasks.add_task(_sync_fanqie)
    return {"status": "started", "message": "番茄同步已在后台启动"}
