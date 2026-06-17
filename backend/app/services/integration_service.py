from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.sqlite_retry import begin_immediate_for_sqlite, retry_sqlite_locked
from app.models.user_integration import UserIntegration
from app.services.secret_store import decrypt_secret, encrypt_secret

WEREAD_PROVIDER = "weread"
WEREAD_INSTALL_COMMAND = "npx skills add Tencent/WeChatReading -g"
WEREAD_DOCS_URL = "https://weread.qq.com/r/weread-skills"


def api_key_hint(api_key: Optional[str]) -> Optional[str]:
    if not api_key:
        return None
    stripped = api_key.strip()
    if len(stripped) <= 8:
        return "*" * len(stripped)
    return f"{stripped[:4]}...{stripped[-4:]}"


def _reset_sync_state(integration: UserIntegration) -> None:
    integration.last_sync_at = None
    integration.last_sync_status = None
    integration.last_sync_error = None


def integration_api_key(integration: Optional[UserIntegration]) -> Optional[str]:
    if not integration or not integration.api_key:
        return None
    return decrypt_secret(integration.api_key)


async def get_user_integration(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
) -> Optional[UserIntegration]:
    result = await db.execute(
        select(UserIntegration).where(
            UserIntegration.user_id == user_id,
            UserIntegration.provider == provider,
        )
    )
    return result.scalar_one_or_none()


async def claim_user_integration_sync(
    db: AsyncSession,
    *,
    integration_id: int,
    lease_seconds: int,
) -> Optional[UserIntegration]:
    """Acquire a per-user integration sync lease."""
    now = datetime.now(timezone.utc)
    lease_cutoff = now - timedelta(seconds=max(int(lease_seconds), 1))

    async def _claim() -> Optional[UserIntegration]:
        await begin_immediate_for_sqlite(db)
        result = await db.execute(select(UserIntegration).where(UserIntegration.id == integration_id).with_for_update())
        integration = result.scalar_one_or_none()
        if integration is None:
            return None

        if (
            integration.last_sync_status == "syncing"
            and integration.last_sync_at is not None
            and integration.last_sync_at > lease_cutoff
        ):
            return None

        integration.last_sync_at = now
        integration.last_sync_status = "syncing"
        integration.last_sync_error = None
        integration.updated_at = now
        await db.flush()
        return integration

    return await retry_sqlite_locked(_claim, on_retry=db.rollback)


async def mark_user_integration_sync_error(
    db: AsyncSession,
    integration: UserIntegration,
    *,
    message: str,
) -> None:
    integration.last_sync_at = datetime.now(timezone.utc)
    integration.last_sync_status = "error"
    integration.last_sync_error = message[:500]
    integration.updated_at = datetime.now(timezone.utc)
    await db.flush()


async def upsert_user_integration(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    api_key: str,
    config: Optional[dict[str, Any]] = None,
) -> UserIntegration:
    integration = await get_user_integration(db, user_id=user_id, provider=provider)
    now = datetime.now(timezone.utc)
    encrypted_api_key = encrypt_secret(api_key)
    if integration:
        integration.api_key = encrypted_api_key
        integration.config = config or {}
        _reset_sync_state(integration)
        integration.updated_at = now
        await db.flush()
        await db.refresh(integration)
        return integration

    integration = UserIntegration(
        user_id=user_id,
        provider=provider,
        api_key=encrypted_api_key,
        config=config or {},
        created_at=now,
        updated_at=now,
    )
    db.add(integration)
    await db.flush()
    await db.refresh(integration)
    return integration


async def clear_user_integration(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
) -> bool:
    integration = await get_user_integration(db, user_id=user_id, provider=provider)
    if not integration:
        return False
    integration.api_key = None
    integration.config = {}
    _reset_sync_state(integration)
    integration.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return True


def integration_status(integration: Optional[UserIntegration], provider: str) -> dict[str, Any]:
    is_weread = provider == WEREAD_PROVIDER
    api_key = integration_api_key(integration)
    return {
        "provider": provider,
        "configured": bool(api_key),
        "api_key_hint": api_key_hint(api_key),
        "config": integration.config if integration and isinstance(integration.config, dict) else {},
        "sync_endpoint_configured": bool(str(settings.WEREAD_SKILL_API_URL or "").strip()) if is_weread else False,
        "install_command": WEREAD_INSTALL_COMMAND if is_weread else None,
        "docs_url": WEREAD_DOCS_URL if is_weread else None,
        "last_sync_at": integration.last_sync_at if integration else None,
        "last_sync_status": integration.last_sync_status if integration else None,
        "last_sync_error": integration.last_sync_error if integration else None,
    }
