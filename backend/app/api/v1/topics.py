"""
Topic clustering API endpoints.

Endpoints:
- POST /api/v1/topics/cluster  — run dedup + clustering
- GET  /api/v1/topics/          — list topic groups
- GET  /api/v1/topics/{id}      — get topic with its items
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, Any

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.models.user import User
from app.models.topic import TopicGroup
from app.models.content import ContentItem
from app.services.topic_clustering import cluster_and_dedup_with_lease
from app.services.zhihu_url import normalize_zhihu_url

router = APIRouter(prefix="/topics", tags=["topics"])


class TopicResponse(BaseModel):
    id: int
    name: str
    summary: str | None = None
    keywords: Any | None = None
    content_count: int
    best_score: float

    model_config = {"from_attributes": True}


class TopicListResponse(BaseModel):
    items: list[TopicResponse]
    total: int


@router.post("/cluster")
async def run_clustering(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_user),
):
    """Run dedup + topic clustering on all analyzed content."""
    stats, claimed = await cluster_and_dedup_with_lease(db, trigger_type="manual")
    if not claimed:
        raise HTTPException(status_code=409, detail="话题聚类正在运行中，请稍后再试")
    return {"status": "ok", "stats": stats}


@router.get("", response_model=TopicListResponse)
async def list_topics(
    db: AsyncSession = Depends(get_db),
):
    """List all topic groups sorted by best_score desc."""
    result = await db.execute(select(TopicGroup).order_by(TopicGroup.best_score.desc()))
    topics = result.scalars().all()

    total_result = await db.execute(select(func.count(TopicGroup.id)))
    total = total_result.scalar() or 0

    return {"items": topics, "total": total}


@router.get("/{topic_id}")
async def get_topic(
    topic_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get topic group with its member content items."""
    result = await db.execute(select(TopicGroup).where(TopicGroup.id == topic_id))
    topic = result.scalar_one_or_none()
    if not topic:
        raise HTTPException(404, "Topic not found")

    items_result = await db.execute(
        select(ContentItem).where(ContentItem.topic_id == topic_id).order_by(ContentItem.crawled_at.desc())
    )
    items = items_result.scalars().all()

    return {
        "topic": TopicResponse.model_validate(topic).model_dump(),
        "items": [
            {
                "id": it.id,
                "title": it.title,
                "url": normalize_zhihu_url(it.url),
                "source_name": it.source_name,
                "duplicate_of": it.duplicate_of,
                "similarity_score": it.similarity_score,
            }
            for it in items
        ],
    }
