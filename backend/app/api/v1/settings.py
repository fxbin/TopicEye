"""
App-level settings API — RSSHub instance management.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone, UTC
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import database_profile, get_db
from app.core.db_backend import database_diagnostics, redact_database_secrets
from app.models.app_setting import AppSetting, DEFAULT_FEATURE_FLAGS
from app.models.app_setting import get_feature_flags_async, set_feature_flags_async

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_admin_user)])

logger = logging.getLogger(__name__)


class RSSHubInstanceItem(BaseModel):
    url: str
    enabled: bool = True
    priority: int = 0
    note: str = ""


class RSSHubInstancesGetResponse(BaseModel):
    instances: list[RSSHubInstanceItem]
    default_instances: list[str]


class RSSHubInstancesUpdateRequest(BaseModel):
    instances: list[RSSHubInstanceItem]


def normalize_rsshub_instance_url(value: str) -> str:
    url = value.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Invalid URL: {value}")
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


@router.get("/rsshub/instances", response_model=RSSHubInstancesGetResponse)
async def get_rsshub_instances(db: AsyncSession = Depends(get_db)):
    """Get current RSSHub instance list (from DB or defaults)."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
    row = result.scalar_one_or_none()

    if row and row.value:
        try:
            raw = json.loads(row.value)
            instances = [RSSHubInstanceItem(**item) for item in raw]
        except json.JSONDecodeError:
            # 存储的 JSON 损坏：当作未配置，但不吞掉 DB/未知异常
            instances = []
        except Exception:
            logger.exception("Failed to parse rsshub_instances setting")
            raise
    else:
        instances = []

    from app.models.app_setting import DEFAULT_RSSHUB_INSTANCES

    return {
        "instances": instances,
        "default_instances": [i["url"] for i in DEFAULT_RSSHUB_INSTANCES],
    }


@router.put("/rsshub/instances")
async def update_rsshub_instances(
    req: RSSHubInstancesUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update RSSHub instance list. Supports enable/disable/add/remove."""
    normalized_instances = []
    seen_urls: set[str] = set()
    for inst in req.instances:
        try:
            url = normalize_rsshub_instance_url(inst.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if url in seen_urls:
            raise HTTPException(status_code=409, detail=f"RSSHub instance already exists: {url}")
        seen_urls.add(url)
        normalized_instances.append(inst.model_copy(update={"url": url}))

    raw_value = json.dumps([inst.model_dump() for inst in normalized_instances], ensure_ascii=False)

    result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = raw_value
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            AppSetting(
                key="rsshub_instances",
                value=raw_value,
                description="RSSHub 实例列表，支持多实例降级",
                updated_at=datetime.now(UTC),
            )
        )

    await db.commit()

    return {"instances": normalized_instances, "updated": True}


# ── DuckDB analytics layer management ──


@router.get("/duckdb/status")
async def duckdb_status():
    """Get DuckDB analytical layer status.

    DuckDB runs in memory and attaches the configured OLTP database read-only.
    No sync step is needed; analytics reads current OLTP data directly.
    """
    try:
        from app.services.duckdb_service import get_analytics

        analytics = get_analytics()
        status = analytics.status()
        available = status["available"]
        diagnostics = database_diagnostics(database_profile)
        return {
            **status,
            "status": "ok" if available else "unavailable",
            "database": diagnostics,
            "architecture": "in-memory DuckDB + OLTP ATTACH (READ_ONLY)",
            "note": "No sync needed; DuckDB reads the configured OLTP backend directly."
            if available
            else "DuckDB package or required extension is unavailable. Analytical read APIs will return 503 until DuckDB is available.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": redact_database_secrets(str(e), database_profile),
        }


# ── Feature flags (功能模块开关) ──────────────────────────────────────


class FeatureFlagsUpdateRequest(BaseModel):
    flags: dict[str, bool]


@router.get("/feature-flags")
async def get_feature_flags(db: AsyncSession = Depends(get_db)):
    """获取功能模块开关列表。DB 为空时回退默认值（所有可选模块默认关）。"""
    flags = await get_feature_flags_async(db)
    return {"flags": flags, "defaults": DEFAULT_FEATURE_FLAGS}


@router.put("/feature-flags")
async def update_feature_flags(
    payload: FeatureFlagsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新功能模块开关（upsert 合并）。返回合并后的完整 flags。"""
    merged = await set_feature_flags_async(payload.flags, db)
    await db.commit()
    return {"flags": merged}


# ── Email provider (邮件服务配置) ─────────────────────────────────────


# 支持的邮件 Provider 列表，前端据此渲染下拉选项
SUPPORTED_EMAIL_PROVIDERS = ["brevo"]

# API Key 脱敏前缀长度
_API_KEY_MASK_PREFIX = 6


class EmailProviderConfigResponse(BaseModel):
    """邮件 Provider 配置响应。api_key 字段脱敏返回。"""

    provider: str = "brevo"
    from_email: str = ""
    from_name: str = "TopicEye"
    api_key_configured: bool = False
    api_key_preview: str = ""
    supported_providers: list[str] = []


class EmailProviderConfigUpdateRequest(BaseModel):
    """邮件 Provider 配置更新请求。

    api_key 为空字符串时保留原值（不修改），非空时覆盖。
    """

    provider: str = "brevo"
    from_email: str = ""
    from_name: str = "TopicEye"
    api_key: str = ""


@router.get("/email-provider", response_model=EmailProviderConfigResponse)
async def get_email_provider_config(db: AsyncSession = Depends(get_db)):
    """获取当前邮件 Provider 配置。api_key 不返回明文，仅返回脱敏预览。"""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "email_provider_config")
    )
    row = result.scalar_one_or_none()

    if not row or not row.value:
        return EmailProviderConfigResponse(supported_providers=SUPPORTED_EMAIL_PROVIDERS)

    try:
        config = json.loads(row.value)
    except json.JSONDecodeError:
        logger.warning("email_provider_config JSON 损坏，返回默认配置")
        return EmailProviderConfigResponse(supported_providers=SUPPORTED_EMAIL_PROVIDERS)

    from app.services.secret_store import decrypt_secret

    api_key_raw = config.get("api_key", "")
    api_key_plain = decrypt_secret(api_key_raw) if api_key_raw else ""
    preview = ""
    if api_key_plain:
        mask_len = min(_API_KEY_MASK_PREFIX, len(api_key_plain))
        preview = api_key_plain[:mask_len] + "****"

    return EmailProviderConfigResponse(
        provider=config.get("provider", "brevo"),
        from_email=config.get("from_email", ""),
        from_name=config.get("from_name", "TopicEye"),
        api_key_configured=bool(api_key_plain),
        api_key_preview=preview,
        supported_providers=SUPPORTED_EMAIL_PROVIDERS,
    )


@router.put("/email-provider")
async def update_email_provider_config(
    payload: EmailProviderConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新邮件 Provider 配置。

    api_key 为空时保留已存储的值（便于修改发件人而不重输 Key）；
    非空时使用 secret_store 加密后覆盖存储。
    """
    if payload.provider not in SUPPORTED_EMAIL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的邮件 Provider: {payload.provider}")

    if not payload.from_email.strip():
        raise HTTPException(status_code=400, detail="发件人邮箱不能为空")

    from app.services.secret_store import encrypt_secret

    # 读取现有配置（用于 api_key 保留逻辑）
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "email_provider_config")
    )
    existing = result.scalar_one_or_none()
    existing_config: dict = {}
    if existing and existing.value:
        try:
            existing_config = json.loads(existing.value)
        except json.JSONDecodeError:
            existing_config = {}

    # api_key 处理：空值保留原值，非空值加密覆盖
    if payload.api_key.strip():
        api_key_stored = encrypt_secret(payload.api_key.strip())
    else:
        api_key_stored = existing_config.get("api_key", "")

    new_config = {
        "provider": payload.provider,
        "from_email": payload.from_email.strip(),
        "from_name": payload.from_name.strip() or "TopicEye",
        "api_key": api_key_stored,
    }
    raw_value = json.dumps(new_config, ensure_ascii=False)

    if existing:
        existing.value = raw_value
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            AppSetting(
                key="email_provider_config",
                value=raw_value,
                description="邮件服务 Provider 配置（api_key 加密存储）",
                updated_at=datetime.now(UTC),
            )
        )

    await db.commit()
    return {"updated": True}
