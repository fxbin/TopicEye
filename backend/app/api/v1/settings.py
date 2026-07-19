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
SUPPORTED_EMAIL_PROVIDERS = ["brevo", "smtp"]

# API Key / SMTP 密码脱敏前缀长度
_SECRET_MASK_PREFIX = 6


class EmailProviderConfigResponse(BaseModel):
    """邮件 Provider 配置响应。敏感字段脱敏返回。"""

    provider: str = "brevo"
    from_email: str = ""
    from_name: str = "TopicEye"
    api_key_configured: bool = False
    api_key_preview: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password_configured: bool = False
    smtp_password_preview: str = ""
    smtp_use_ssl: bool = False
    supported_providers: list[str] = []


class EmailProviderConfigUpdateRequest(BaseModel):
    """邮件 Provider 配置更新请求。

    api_key / smtp_password 为空字符串时保留原值（不修改），非空时覆盖。
    SMTP 字段仅在 provider == 'smtp' 时生效。
    """

    provider: str = "brevo"
    from_email: str = ""
    from_name: str = "TopicEye"
    api_key: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_use_ssl: bool = False


@router.get("/email-provider", response_model=EmailProviderConfigResponse)
async def get_email_provider_config(db: AsyncSession = Depends(get_db)):
    """获取当前邮件 Provider 配置。敏感字段（api_key / smtp_password）不返回明文，仅返回脱敏预览。"""
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

    def _mask(plain: str) -> str:
        if not plain:
            return ""
        mask_len = min(_SECRET_MASK_PREFIX, len(plain))
        return plain[:mask_len] + "****"

    api_key_plain = decrypt_secret(config.get("api_key", "")) or ""
    smtp_password_plain = decrypt_secret(config.get("smtp_password", "")) or ""

    return EmailProviderConfigResponse(
        provider=config.get("provider", "brevo"),
        from_email=config.get("from_email", ""),
        from_name=config.get("from_name", "TopicEye"),
        api_key_configured=bool(api_key_plain),
        api_key_preview=_mask(api_key_plain),
        smtp_host=config.get("smtp_host", ""),
        smtp_port=int(config.get("smtp_port", 587)),
        smtp_username=config.get("smtp_username", ""),
        smtp_password_configured=bool(smtp_password_plain),
        smtp_password_preview=_mask(smtp_password_plain),
        smtp_use_ssl=bool(config.get("smtp_use_ssl", False)),
        supported_providers=SUPPORTED_EMAIL_PROVIDERS,
    )


@router.put("/email-provider")
async def update_email_provider_config(
    payload: EmailProviderConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新邮件 Provider 配置。

    敏感字段（api_key / smtp_password）为空时保留原值，非空时加密覆盖。
    SMTP 专属字段仅在 provider == 'smtp' 时校验必填。
    """
    if payload.provider not in SUPPORTED_EMAIL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"不支持的邮件 Provider: {payload.provider}")

    if not payload.from_email.strip():
        raise HTTPException(status_code=400, detail="发件人邮箱不能为空")

    # SMTP 必填校验
    if payload.provider == "smtp":
        if not payload.smtp_host.strip():
            raise HTTPException(status_code=400, detail="SMTP 服务器不能为空")
        if not payload.smtp_username.strip():
            raise HTTPException(status_code=400, detail="SMTP 用户名不能为空")

    from app.services.secret_store import encrypt_secret

    # 读取现有配置（用于敏感字段保留逻辑）
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

    # 敏感字段处理：空值保留原值，非空值加密覆盖
    api_key_stored = (
        encrypt_secret(payload.api_key.strip())
        if payload.api_key.strip()
        else existing_config.get("api_key", "")
    )
    smtp_password_stored = (
        encrypt_secret(payload.smtp_password.strip())
        if payload.smtp_password.strip()
        else existing_config.get("smtp_password", "")
    )

    new_config = {
        "provider": payload.provider,
        "from_email": payload.from_email.strip(),
        "from_name": payload.from_name.strip() or "TopicEye",
        "api_key": api_key_stored,
        "smtp_host": payload.smtp_host.strip(),
        "smtp_port": int(payload.smtp_port) if payload.smtp_port else 587,
        "smtp_username": payload.smtp_username.strip(),
        "smtp_password": smtp_password_stored,
        "smtp_use_ssl": bool(payload.smtp_use_ssl),
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
                description="邮件服务 Provider 配置（敏感字段加密存储）",
                updated_at=datetime.now(UTC),
            )
        )

    await db.commit()
    return {"updated": True}


# ── Notification webhook (通知推送 / 飞书·钉钉·Slack) ────────────────────
#
# 用于运营通知推送（信源失败告警等）。webhook URL 含 token，按半敏感字段处理：
# 加密存储（secret_store），GET 返回脱敏预览 + configured 标志，PUT 时空值保留原值。
# 高级推送能力（卡片消息、日报、精选内容）为后续阶段，当前仅做配置入口。


class NotificationWebhookConfigResponse(BaseModel):
    """通知推送 webhook 配置响应。webhook_url 脱敏返回。"""

    enabled: bool = False
    webhook_url_configured: bool = False
    webhook_url_preview: str = ""
    note: str = ""


class NotificationWebhookConfigUpdateRequest(BaseModel):
    """通知推送 webhook 配置更新请求。

    webhook_url 为空字符串时保留原值（不修改），非空时覆盖。
    传空字符串且原值存在时不会清空——如需清空请传显式空 URL 后禁用 enabled。
    """

    enabled: bool = False
    webhook_url: str = ""
    note: str = ""


def _validate_webhook_url(value: str) -> str:
    """校验 webhook URL：必须 http/https 且有 netloc。"""
    url = value.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Invalid webhook URL: {value}")
    return url


@router.get("/notification-webhook", response_model=NotificationWebhookConfigResponse)
async def get_notification_webhook_config(db: AsyncSession = Depends(get_db)):
    """获取当前通知推送 webhook 配置。webhook_url 不返回明文，仅返回脱敏预览。"""
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "notification_webhook_config")
    )
    row = result.scalar_one_or_none()

    if not row or not row.value:
        return NotificationWebhookConfigResponse()

    try:
        config = json.loads(row.value)
    except json.JSONDecodeError:
        logger.warning("notification_webhook_config JSON 损坏，返回默认配置")
        return NotificationWebhookConfigResponse()

    from app.services.secret_store import decrypt_secret

    webhook_plain = decrypt_secret(config.get("webhook_url", "")) or ""

    def _mask(plain: str) -> str:
        if not plain:
            return ""
        # 保留 scheme + host 前缀，路径/token 用 **** 遮蔽
        parts = urlsplit(plain)
        host = parts.netloc or ""
        preview_host = host[: _SECRET_MASK_PREFIX] if host else ""
        return f"{parts.scheme}://{preview_host}****"

    return NotificationWebhookConfigResponse(
        enabled=bool(config.get("enabled", False)),
        webhook_url_configured=bool(webhook_plain),
        webhook_url_preview=_mask(webhook_plain),
        note=config.get("note", ""),
    )


@router.put("/notification-webhook")
async def update_notification_webhook_config(
    payload: NotificationWebhookConfigUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """更新通知推送 webhook 配置。

    webhook_url 为空时保留原值，非空时校验并加密覆盖。
    """
    from app.services.secret_store import encrypt_secret

    # 读取现有配置（用于 webhook_url 保留逻辑）
    result = await db.execute(
        select(AppSetting).where(AppSetting.key == "notification_webhook_config")
    )
    existing = result.scalar_one_or_none()
    existing_config: dict = {}
    if existing and existing.value:
        try:
            existing_config = json.loads(existing.value)
        except json.JSONDecodeError:
            existing_config = {}

    # webhook_url 处理：空值保留原值，非空值校验+加密覆盖
    new_url_raw = payload.webhook_url.strip()
    if new_url_raw:
        try:
            validated_url = _validate_webhook_url(new_url_raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        webhook_url_stored = encrypt_secret(validated_url) or ""
    else:
        webhook_url_stored = existing_config.get("webhook_url", "")

    new_config = {
        "enabled": bool(payload.enabled),
        "webhook_url": webhook_url_stored,
        "note": payload.note.strip(),
    }
    raw_value = json.dumps(new_config, ensure_ascii=False)

    if existing:
        existing.value = raw_value
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            AppSetting(
                key="notification_webhook_config",
                value=raw_value,
                description="通知推送 webhook 配置（webhook_url 加密存储）",
                updated_at=datetime.now(UTC),
            )
        )

    await db.commit()
    return {"updated": True}
