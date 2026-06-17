"""
母题相关 API。
提供母题的 CRUD、关键词打分、内容匹配接口。
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.models.mother_topic import MotherTopic
from app.models.content import ContentItem
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/mother-topics", tags=["母题"])


# ── Pydantic 请求/响应模型 ─────────────────────────────────────────────


class MotherTopicBase(BaseModel):
    name: str
    description: str | None = None
    keywords: list[str] = []
    weight: float = 1.0
    content_type: str | None = None
    target_reader: str | None = None
    is_active: bool = True
    display_order: int = 0


class MotherTopicCreate(MotherTopicBase):
    pass


class MotherTopicUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    keywords: list[str] | None = None
    weight: float | None = None
    content_type: str | None = None
    target_reader: str | None = None
    is_active: bool | None = None
    display_order: int | None = None


class MotherTopicOut(MotherTopicBase):
    id: int
    created_at: str | None = None
    updated_at: str | None = None

    model_config = {"from_attributes": True}

    @classmethod
    def from_orm_model(cls, obj) -> MotherTopicOut:
        """Convert SQLAlchemy model to dict, serializing datetimes."""
        d = {
            "id": obj.id,
            "name": obj.name,
            "description": obj.description,
            "keywords": obj.keywords,
            "weight": obj.weight,
            "content_type": obj.content_type,
            "target_reader": obj.target_reader,
            "is_active": obj.is_active,
            "display_order": obj.display_order,
            "created_at": obj.created_at.isoformat() if obj.created_at else None,
            "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
        }
        return cls(**d)


class ContentScoringRequest(BaseModel):
    title: str
    summary: str | None = ""
    source: str | None = None
    hot_value: int = 0


class ContentScoringResult(BaseModel):
    title: str
    topic_scores: list[dict]  # [{name, score, weight, final}]
    top_topic: str | None
    final_score: float


# ── 路由 ─────────────────────────────────────────────────────────────


@router.get("", response_model=list[MotherTopicOut], include_in_schema=False)
@router.get("/", response_model=list[MotherTopicOut])
async def list_mother_topics(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出所有母题，支持只返回激活的。"""
    if not active_only and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    stmt = select(MotherTopic).order_by(MotherTopic.display_order, MotherTopic.id)
    if active_only:
        stmt = stmt.where(MotherTopic.is_active == True)
    result = await db.execute(stmt)
    topics = result.scalars().all()
    return [MotherTopicOut.from_orm_model(t) for t in topics]


@router.post("", response_model=MotherTopicOut, include_in_schema=False)
@router.post("/", response_model=MotherTopicOut)
async def create_mother_topic(
    topic_in: MotherTopicCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """创建新母题。"""
    topic = MotherTopic(
        name=topic_in.name,
        description=topic_in.description,
        keywords=topic_in.keywords,
        weight=topic_in.weight,
        content_type=topic_in.content_type,
        target_reader=topic_in.target_reader,
        is_active=topic_in.is_active,
        display_order=topic_in.display_order,
    )
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return MotherTopicOut.from_orm_model(topic)


@router.put("/{topic_id}", response_model=MotherTopicOut)
async def update_mother_topic(
    topic_id: int,
    update_in: MotherTopicUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """更新母题。"""
    topic = await db.get(MotherTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="母题不存在")
    for field, value in update_in.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(topic, field, value)
    await db.commit()
    await db.refresh(topic)
    return MotherTopicOut.from_orm_model(topic)


@router.delete("/{topic_id}")
async def delete_mother_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """删除母题（软删除：is_active=False）。"""
    topic = await db.get(MotherTopic, topic_id)
    if not topic:
        raise HTTPException(status_code=404, detail="母题不存在")
    topic.is_active = False
    await db.commit()
    return {"ok": True, "message": "母题已停用"}


@router.post("/score", response_model=ContentScoringResult)
async def score_content(
    req: ContentScoringRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    对单条内容按母题打分。
    用于：选题候选打分、我的母题页过滤。
    """
    text = f"{req.title} {req.summary or ''}"

    # 获取激活的母题
    result = await db.execute(
        select(MotherTopic).where(MotherTopic.is_active == True).order_by(MotherTopic.display_order)
    )
    topics = result.scalars().all()

    if not topics:
        return ContentScoringResult(
            title=req.title,
            topic_scores=[],
            top_topic=None,
            final_score=0.0,
        )

    topic_scores = []
    for topic in topics:
        keyword_score = topic.match_score(text)
        # 来源新鲜度（简化：直接用 hot_value / 1000 作为基础分）
        freshness = min(1.0, req.hot_value / 10000)
        # 母题匹配分 × 权重 + 新鲜度加成（0.0 ~ 1.1）
        raw = keyword_score * topic.weight + freshness * 0.1
        # 归一化到 0-100，理论上限约 110
        final = round(min(raw * (100 / 1.1), 100), 1)
        topic_scores.append(
            {
                "name": topic.name,
                "keyword_score": round(keyword_score, 3),
                "weight": topic.weight,
                "freshness": round(freshness, 3),
                "final": final,
            }
        )

    # 按最终分数排序
    topic_scores.sort(key=lambda x: x["final"], reverse=True)
    top = topic_scores[0] if topic_scores else None

    final_score = top["final"] if top else 0.0

    return ContentScoringResult(
        title=req.title,
        topic_scores=topic_scores,
        top_topic=top["name"] if top else None,
        final_score=final_score,
    )


class BatchScoringRequest(BaseModel):
    items: list[ContentScoringRequest]


class BatchScoringResult(BaseModel):
    results: list[ContentScoringResult]


@router.post("/score-batch", response_model=BatchScoringResult)
async def score_content_batch(
    req: BatchScoringRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量对多条内容按母题打分。
    只查一次 DB 获取所有活跃母题，然后循环打分。
    """
    # 一次性加载所有活跃母题
    result = await db.execute(
        select(MotherTopic).where(MotherTopic.is_active == True).order_by(MotherTopic.display_order)
    )
    topics = result.scalars().all()

    if not topics:
        return BatchScoringResult(
            results=[
                ContentScoringResult(
                    title=item.title,
                    topic_scores=[],
                    top_topic=None,
                    final_score=0.0,
                )
                for item in req.items
            ]
        )

    results: list[ContentScoringResult] = []
    for item in req.items:
        text = f"{item.title} {item.summary or ''}"
        freshness = min(1.0, item.hot_value / 10000)

        topic_scores = []
        for topic in topics:
            keyword_score = topic.match_score(text)
            raw = keyword_score * topic.weight + freshness * 0.1
            final = round(min(raw * (100 / 1.1), 100), 1)
            topic_scores.append(
                {
                    "name": topic.name,
                    "keyword_score": round(keyword_score, 3),
                    "weight": topic.weight,
                    "freshness": round(freshness, 3),
                    "final": final,
                }
            )

        topic_scores.sort(key=lambda x: x["final"], reverse=True)
        top = topic_scores[0] if topic_scores else None
        final_score = top["final"] if top else 0.0

        results.append(
            ContentScoringResult(
                title=item.title,
                topic_scores=topic_scores,
                top_topic=top["name"] if top else None,
                final_score=final_score,
            )
        )

    return BatchScoringResult(results=results)


@router.get("/match/{content_id}")
async def match_content_to_topics(
    content_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """对已入库的内容重新匹配母题。"""
    content = await db.get(ContentItem, content_id)
    if not content:
        raise HTTPException(status_code=404, detail="内容不存在")

    text = f"{content.title} {content.summary or ''}"

    result = await db.execute(
        select(MotherTopic).where(MotherTopic.is_active == True).order_by(MotherTopic.display_order)
    )
    topics = result.scalars().all()

    topic_scores = []
    for topic in topics:
        keyword_score = topic.match_score(text)
        final = round(keyword_score * topic.weight, 3)
        topic_scores.append(
            {
                "name": topic.name,
                "keyword_score": round(keyword_score, 3),
                "weight": topic.weight,
                "final": final,
            }
        )

    topic_scores.sort(key=lambda x: x["final"], reverse=True)
    top = topic_scores[0] if topic_scores else None

    return {
        "content_id": content_id,
        "title": content.title,
        "top_topic": top["name"] if top else None,
        "top_score": top["final"] if top else 0.0,
        "all_scores": topic_scores,
    }
