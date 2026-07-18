"""
个人 API access token CRUD。

用途：脚本/CI 场景调用 API，区别于浏览器登录会话。

- POST   /me/api-tokens          创建（返回明文 token，仅此一次）
- GET    /me/api-tokens          列出自己的 token
- POST   /me/api-tokens/{id}/revoke  撤销
- DELETE /me/api-tokens/{id}     删除
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_user
from app.core.database import get_db
from app.models.user import User
from app.services.auth_service import (
    create_api_token,
    delete_api_token,
    list_api_tokens,
    revoke_api_token,
)

router = APIRouter(
    prefix="/me/api-tokens",
    tags=["user-api-tokens"],
    dependencies=[Depends(get_current_user)],
)


class CreateApiTokenRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, description="可读名字，如 'CI 脚本'")
    expires_at: datetime | None = Field(None, description="可选过期时间，ISO 格式")


def _token_to_dict(t) -> dict:
    return {
        "id": t.id,
        "name": t.name,
        "token_prefix": t.token_prefix,
        "expires_at": t.expires_at.isoformat() if t.expires_at else None,
        "revoked_at": t.revoked_at.isoformat() if t.revoked_at else None,
        "last_used_at": t.last_used_at.isoformat() if t.last_used_at else None,
        "created_at": t.created_at.isoformat() if t.created_at else None,
    }


@router.post("", status_code=201)
async def create_token(
    req: CreateApiTokenRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """创建 API token。**明文 token 仅在此次响应返回一次**。"""
    raw, record = await create_api_token(
        db,
        user_id=current_user.id,
        name=req.name,
        expires_at=req.expires_at,
    )
    await db.commit()
    return {
        "token": raw,  # 明文 token（仅此一次）
        "record": _token_to_dict(record),
    }


@router.get("")
async def list_tokens(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出当前用户的所有 API token（含已撤销）。"""
    tokens = await list_api_tokens(db, current_user.id)
    return {
        "count": len(tokens),
        "tokens": [_token_to_dict(t) for t in tokens],
    }


@router.post("/{token_id}/revoke")
async def revoke_token(
    token_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """撤销 API token（per-user 校验）。"""
    ok = await revoke_api_token(db, user_id=current_user.id, token_id=token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token 不存在或已撤销")
    await db.commit()
    return {"success": ok}


@router.delete("/{token_id}", status_code=204)
async def delete_token(
    token_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除 API token（per-user 校验）。"""
    ok = await delete_api_token(db, user_id=current_user.id, token_id=token_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Token 不存在")
    await db.commit()
