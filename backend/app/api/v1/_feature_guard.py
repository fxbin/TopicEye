"""Feature-flag 请求守卫。

为可运营的功能模块（如网文雷达）提供 per-request 的 DB flag 检查。
路由永远注册（FastAPI 要求），但每次请求查 DB flag，关闭则返回 404
（而非 403，避免暴露功能存在给未授权探测）。
"""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.app_setting import get_feature_flag_async


def require_feature(flag_key: str):
    """生成一个 FastAPI 依赖，请求时查 DB 的 feature flag，关闭则 404。

    用法：router.include_router(xxx_router, dependencies=[Depends(require_feature("webnovel_module"))])
    """

    async def _guard(db: AsyncSession = Depends(get_db)):
        if not await get_feature_flag_async(db, flag_key):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="此功能未启用")
        return True

    return _guard
