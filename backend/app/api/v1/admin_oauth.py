"""管理员后台：第三方登录（OAuth）provider 配置（#94）。

- GET  /admin/oauth/providers          列出全部受支持 provider 的配置状态（secret 只回传是否已配置）
- PUT  /admin/oauth/providers/{name}   保存凭据 + 启用开关，即时生效

密钥处理沿用 llm_models 的范式：GET 永不回传 secret 明文/密文；
PUT 留空表示保留现有值；is_encrypted_secret 守卫防止已加密值被二次加密。
"""

from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import get_db
from app.models.oauth_provider import SUPPORTED_OAUTH_PROVIDERS
from app.repositories.oauth_provider_repo import OAuthProviderRepository
from app.services.secret_store import encrypt_secret, is_encrypted_secret

router = APIRouter(prefix="/admin/oauth", tags=["admin-oauth"], dependencies=[Depends(get_current_admin_user)])

logger = logging.getLogger(__name__)


def _normalize_optional(value: str | None) -> str | None:
    """空白输入归一为 None，避免把纯空格存成凭据。

    str() 兜底与 llm_models._normalize_optional_config_value 同源：
    非字符串入参（畸形报文）走 422 而不是校验器内 AttributeError 500。
    """
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


class OAuthProviderItem(BaseModel):
    provider: str
    client_id: str | None = None
    enabled: bool = False
    client_secret_configured: bool = False
    updated_at: datetime | None = None


class OAuthProvidersResponse(BaseModel):
    providers: list[OAuthProviderItem]


class OAuthProviderUpdateRequest(BaseModel):
    client_id: str | None = None
    # None / 空串 = 保留库中现有密文；非空 = 覆盖（服务端加密后落库）
    client_secret: str | None = None
    enabled: bool = False

    @field_validator("client_id", "client_secret", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value):
        return _normalize_optional(value)


def _item_from_row(provider: str, row=None) -> OAuthProviderItem:
    """行不存在时按「未配置 + 未启用」返回，保证 GET 形状稳定。"""
    if row is None:
        return OAuthProviderItem(provider=provider)
    return OAuthProviderItem(
        provider=provider,
        client_id=row.client_id,
        enabled=row.enabled,
        client_secret_configured=bool(row.client_secret),
        updated_at=row.updated_at,
    )


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_oauth_providers(db: AsyncSession = Depends(get_db)):
    """列出受支持 provider 的配置状态（含未落库的，方便后台渲染固定两档）。"""
    rows = {row.provider: row for row in await OAuthProviderRepository(db).list_all()}
    return {"providers": [_item_from_row(name, rows.get(name)) for name in SUPPORTED_OAUTH_PROVIDERS]}


@router.put("/providers/{provider}", response_model=OAuthProviderItem)
async def update_oauth_provider(provider: str, req: OAuthProviderUpdateRequest, db: AsyncSession = Depends(get_db)):
    """保存单个 provider 的凭据与开关。

    - secret 留空 = 保留现有密文；覆盖时加密落库
    - 启用校验：client_id 与 client_secret（新值或库存值）必须同时存在
    """
    if provider not in SUPPORTED_OAUTH_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"不支持的 OAuth provider: {provider}",
        )

    repo = OAuthProviderRepository(db)
    existing = await repo.get_by_provider(provider)

    new_secret = existing.client_secret if existing is not None else None
    if req.client_secret:
        # 守卫：已是 enc:v1: 密文的输入直接采用，防止迁移脚本或回显误传导致二次加密
        new_secret = req.client_secret if is_encrypted_secret(req.client_secret) else encrypt_secret(req.client_secret)

    if req.enabled and (not req.client_id or not new_secret):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="启用前需同时配置 client_id 与 client_secret",
        )

    row = await repo.upsert_provider(
        provider,
        client_id=req.client_id,
        client_secret=new_secret,
        enabled=req.enabled,
    )
    await db.commit()
    logger.info(
        "OAuth provider config updated: provider=%s enabled=%s secret_changed=%s",
        provider,
        req.enabled,
        bool(req.client_secret),
    )
    return _item_from_row(provider, row)
