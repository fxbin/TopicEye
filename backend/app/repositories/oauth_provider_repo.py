"""
Repository for OAuthProvider model operations.

封装 oauth_providers 表的查询与 upsert：
- 按 provider 查询单条凭据
- 列出全部已落库的 provider 凭据
- upsert by provider（client_id / 加密后的 client_secret / enabled）

不处理 commit 与加解密，事务边界由调用方（service/endpoint）负责，
加解密属于 app/services/oauth_provider_service.py 的编排职责。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.models.oauth_provider import OAuthProvider
from app.repositories.base import BaseRepository


class OAuthProviderRepository(BaseRepository[OAuthProvider]):
    """OAuthProvider CRUD（按 provider 主键）。"""

    model = OAuthProvider

    async def get_by_provider(self, provider: str) -> OAuthProvider | None:
        """按 provider 名查询单条凭据，不存在返回 None。"""
        result = await self.db.execute(select(OAuthProvider).where(OAuthProvider.provider == provider))
        return result.scalar_one_or_none()

    async def list_all(self) -> list[OAuthProvider]:
        """列出全部已落库的 provider 凭据（未配置的 provider 不在表中）。"""
        result = await self.db.execute(select(OAuthProvider))
        return list(result.scalars().all())

    async def upsert_provider(
        self,
        provider: str,
        *,
        client_id: str | None,
        client_secret: str | None,
        enabled: bool,
    ) -> OAuthProvider:
        """按 provider upsert 凭据。不 commit，调用方负责事务边界。

        client_secret 必须是调用方已加密的密文（enc:v1:）或 None（表示清除）；
        本层不做加解密，避免职责越界。
        """
        row = await self.get_by_provider(provider)
        now = datetime.now(UTC)
        if row is not None:
            row.client_id = client_id
            row.client_secret = client_secret
            row.enabled = enabled
            row.updated_at = now
            return row
        new_row = OAuthProvider(
            provider=provider,
            client_id=client_id,
            client_secret=client_secret,
            enabled=enabled,
            updated_at=now,
        )
        self.db.add(new_row)
        return new_row
