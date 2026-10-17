"""Repository for MCPOAuthToken — access / refresh token 查询与 family 撤销。"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.models.mcp_oauth import MCPOAuthToken
from app.repositories.base import BaseRepository


class MCPOAuthTokenRepository(BaseRepository[MCPOAuthToken]):
    """MCPOAuthToken CRUD + family 级联撤销。"""

    model = MCPOAuthToken

    async def get_by_token_hash(self, token_hash: str) -> MCPOAuthToken | None:
        result = await self.db.execute(select(MCPOAuthToken).where(MCPOAuthToken.token_hash == token_hash))
        return result.scalar_one_or_none()

    async def revoke_by_id_if_active(self, token_id: int) -> bool:
        """单行原子撤销（仅当未撤销时生效）；轮换并发竞争下只有一路成功。"""
        result = await self.db.execute(
            update(MCPOAuthToken)
            .where(MCPOAuthToken.id == token_id, MCPOAuthToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return bool(result.rowcount)

    async def revoke_family(self, family_id: str) -> int:
        """撤销整个轮换链（access + refresh）；幂等，返回撤销行数。"""
        result = await self.db.execute(
            update(MCPOAuthToken)
            .where(MCPOAuthToken.family_id == family_id, MCPOAuthToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC))
        )
        return result.rowcount or 0

    async def delete_stale(self, older_than: datetime) -> int:
        """删除早已过期且被撤销超过保留期的 token 行（保留近期行便于排障）。"""
        result = await self.db.execute(
            delete(MCPOAuthToken).where(MCPOAuthToken.expires_at < older_than, MCPOAuthToken.revoked_at.isnot(None))
        )
        return result.rowcount or 0
