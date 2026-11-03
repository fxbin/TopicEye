"""
Admin Prompt Registry API — read-only prompt catalog + usage stats.

- GET /admin/prompts          List all registered prompts with recent call stats
- GET /admin/prompts/{id}     Get full prompt content + detailed usage
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.services.prompt_registry_service import list_prompt_catalog, prompt_catalog_detail

router = APIRouter(
    prefix="/admin/prompts",
    tags=["admin-prompts"],
    dependencies=[Depends(get_current_admin_user)],
)


@router.get("")
async def list_prompts(
    scene: str | None = Query(None, description="按 scene 过滤"),
    db: AsyncSession = Depends(get_db),
):
    """List all registered prompts with recent 7-day call statistics."""
    cutoff = datetime.now(UTC) - timedelta(days=7)
    return await list_prompt_catalog(db, scene, cutoff)


@router.get("/{prompt_id}")
async def get_prompt_detail(
    prompt_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get full prompt content + detailed 30-day usage statistics."""
    cutoff_30d = datetime.now(UTC) - timedelta(days=30)
    detail = await prompt_catalog_detail(db, prompt_id, cutoff_30d)
    if detail is None:
        raise HTTPException(status_code=404, detail="Prompt not found")
    return detail
