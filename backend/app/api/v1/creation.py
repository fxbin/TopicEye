"""
Creation plan API endpoints.

- POST /creation/plan       生成新方案（同步写入 creation_plans 历史）
- GET  /creation/platforms  可用平台
- GET  /creation/plans      列出当前用户的历史方案
- GET  /creation/plans/{id} 获取单条历史方案详情
- DELETE /creation/plans/{id} 删除自己的一条历史方案
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import async_session
from app.models.user import User
from app.repositories.creation_repo import CreationPlanRepository
from app.services.creation import generate_creation_plan, PLATFORM_PROMPTS

router = APIRouter(prefix="/creation", tags=["creation"], dependencies=[Depends(get_current_user)])
logger = logging.getLogger(__name__)


class CreationRequest(BaseModel):
    content_id: int
    platform: str  # xiaohongshu / short_video / wechat


@router.post("/plan")
async def create_plan(
    req: CreationRequest,
    current_user: User = Depends(get_current_user),
):
    """Generate a creation plan for a content item on a specific platform."""
    if req.platform not in PLATFORM_PROMPTS:
        raise HTTPException(
            status_code=400, detail=f"Unsupported platform: {req.platform}. Supported: {list(PLATFORM_PROMPTS.keys())}"
        )
    async with async_session() as db:
        result = await generate_creation_plan(db, req.content_id, req.platform, user_id=current_user.id)
    if "error" in result:
        logger.warning("Creation plan failed: user_id=%d, content_id=%d, platform=%s, error=%s", current_user.id, req.content_id, req.platform, result["error"])
        raise HTTPException(status_code=400, detail=result["error"])
    logger.info("Creation plan generated: user_id=%d, content_id=%d, platform=%s", current_user.id, req.content_id, req.platform)
    return result


@router.get("/platforms")
async def list_platforms():
    """List available creation platforms."""
    return {"platforms": [{"id": k, "name": v["name"]} for k, v in PLATFORM_PROMPTS.items()]}


def _plan_to_dict(p: Any) -> dict:
    return {
        "id": p.id,
        "user_id": p.user_id,
        "content_id": p.content_id,
        "content_title": p.content_title_snapshot,
        "platform": p.platform,
        "platform_name": p.platform_name,
        "plan": p.plan,
        "error": p.error,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


@router.get("/plans")
async def list_my_plans(
    platform: str | None = Query(None, description="按平台过滤"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的历史创作方案（per-user 隔离）。"""
    async with async_session() as db:
        repo = CreationPlanRepository(db)
        items = await repo.list_user_plans(
            user_id=current_user.id,
            platform=platform,
            limit=limit,
            offset=offset,
        )
    return {
        "count": len(items),
        "plans": [_plan_to_dict(p) for p in items],
    }


@router.get("/plans/{plan_id}")
async def get_my_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
):
    """获取单条历史方案详情（per-user 隔离）。"""
    async with async_session() as db:
        repo = CreationPlanRepository(db)
        plan = await repo.get_user_plan(plan_id, current_user.id)
    if plan is None:
        raise HTTPException(status_code=404, detail="方案不存在")
    return _plan_to_dict(plan)


@router.delete("/plans/{plan_id}", status_code=204)
async def delete_my_plan(
    plan_id: int,
    current_user: User = Depends(get_current_user),
):
    """删除自己的一条历史方案（per-user 隔离）。"""
    async with async_session() as db:
        repo = CreationPlanRepository(db)
        rowcount = await repo.delete_user_plan(plan_id, current_user.id)
        await db.commit()
    if rowcount == 0:
        raise HTTPException(status_code=404, detail="方案不存在")
