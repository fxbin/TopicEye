"""Model catalog API endpoints — models.dev 目录查询。

  GET  /models/catalog/providers        — 精选分组 provider 清单（?include_all=true 附带全部）
  GET  /models/catalog/models           — 按 provider 列目录模型（支持 search）
  POST /models/catalog/refresh          — 手动触发全量刷新（管理员）

目录是参考数据：只读为主，refresh 是唯一的写入口。价格/上下文窗口
仅用于表单预填，永不写回 llm_models。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user, get_current_user
from app.core.database import get_db
from app.services import model_catalog_service

router = APIRouter(prefix="/models/catalog", tags=["models"])
logger = logging.getLogger(__name__)


@router.get("/providers")
async def list_catalog_providers(
    include_all: bool = Query(False, description="附带全部非精选 provider（按模型数倒序）"),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    """精选 provider 清单（分组 + litellm 映射 + 默认 api_base + 模型数）。"""
    return await model_catalog_service.list_providers_payload(db, include_all=include_all)


@router.get("/models")
async def list_catalog_models(
    provider: str = Query(
        ..., min_length=1, max_length=50, description="models.dev provider id 或 litellm provider 名"
    ),
    search: str | None = Query(None, max_length=100),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(get_current_user),
):
    """按 provider 列目录模型，供表单 Model ID 自动补全与价格预填。"""
    return await model_catalog_service.list_models_payload(
        db,
        provider=provider,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post("/refresh", dependencies=[Depends(get_current_admin_user)])
async def refresh_model_catalog(db: AsyncSession = Depends(get_db)):
    """手动触发 models.dev 全量刷新。失败保留旧数据并返回 502。"""
    try:
        summary = await model_catalog_service.refresh_catalog(db)
        await db.commit()
        return summary
    except Exception as exc:
        logger.warning("Manual model catalog refresh failed: %s", exc)
        raise HTTPException(
            status_code=502,
            detail=f"模型目录刷新失败（旧数据保留）：{exc}",
        ) from exc
