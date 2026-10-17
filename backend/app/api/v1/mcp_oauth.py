"""MCP OAuth 同意页交互端点（cookie 会话认证）。

浏览器弹窗登录流程中，前端 ``/mcp/authorize`` 同意页与后端的交互面：
- GET  /mcp-oauth/authorize-info — 展示待授权客户端信息（client_name 等）
- POST /mcp-oauth/approve        — 用户批准，返回带 code 的客户端回调地址
- POST /mcp-oauth/deny           — 用户拒绝，返回 error=access_denied 回调地址

授权码签发、TTL、单次性语义在 ``app/services/mcp_oauth_service.py``；
本层只做会话校验（get_current_user）与 response shaping。三个端点都
要求操作者是授权请求的**发起者**（service 层校验 initiator_user_id，
非发起者一律 404 不暴露存在性）——发起者绑定由 ``app/mcp/authorize_route.py``
的 /authorize 包装路由落库，request_id 是 uuid4（≈122 bit 熵）、
10 分钟过期且一次性。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services import mcp_oauth_service

router = APIRouter(
    prefix="/mcp-oauth",
    tags=["mcp-oauth"],
    dependencies=[Depends(get_current_user)],
)
logger = logging.getLogger(__name__)

_GONE = "授权请求不存在、已过期或已被处理"


class ConsentDecisionRequest(BaseModel):
    request_id: str = Field(..., min_length=1, max_length=36, description="/authorize 下发的待授权请求 id")


@router.get("/authorize-info")
async def get_authorize_info(
    request_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """同意页展示信息：应用名、主页、请求的 scope 与回调目标主机（仅发起者）。"""
    info = await mcp_oauth_service.get_authorization_info(db, request_id, viewer_user_id=current_user.id)
    if info is None:
        raise HTTPException(status_code=404, detail=_GONE)
    return info


@router.post("/approve")
async def approve_authorization(
    req: ConsentDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """批准授权：绑定当前用户并签发一次性授权码，返回客户端回调地址。"""
    result = await mcp_oauth_service.approve_authorization(db, req.request_id, current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail=_GONE)
    _code, redirect_to = result
    await db.commit()
    logger.info("MCP OAuth approved: user_id=%d client=%s", current_user.id, req.request_id)
    # redirect_to 已含一次性 code；前端 window.location 跳转即可
    return {"redirect_to": redirect_to}


@router.post("/deny")
async def deny_authorization(
    req: ConsentDecisionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """拒绝授权：按 RFC 6749 以 error=access_denied 回调客户端（仅发起者）。"""
    redirect_to = await mcp_oauth_service.deny_authorization(db, req.request_id, acting_user_id=current_user.id)
    if redirect_to is None:
        raise HTTPException(status_code=404, detail=_GONE)
    await db.commit()
    return {"redirect_to": redirect_to}
