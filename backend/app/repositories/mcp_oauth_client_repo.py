"""Repository for MCPOAuthClient — DCR 注册的 MCP OAuth 客户端查询。

只做查询与落库；secret 加解密在 service（secret_store），事务由调用方负责。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, or_, select, text, update

from app.models.mcp_oauth import MCPOAuthAuthorization, MCPOAuthClient, MCPOAuthToken
from app.repositories.base import BaseRepository


class MCPOAuthClientRepository(BaseRepository[MCPOAuthClient]):
    """MCPOAuthClient CRUD。"""

    model = MCPOAuthClient

    async def get_by_client_id(self, client_id: str) -> MCPOAuthClient | None:
        result = await self.db.execute(select(MCPOAuthClient).where(MCPOAuthClient.client_id == client_id))
        return result.scalar_one_or_none()

    async def lock_by_client_id(self, client_id: str) -> MCPOAuthClient | None:
        """Lifecycle writers lock the parent before mutating authorization/token rows."""
        result = await self.db.execute(
            select(MCPOAuthClient)
            .where(MCPOAuthClient.client_id == client_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def remember_authorized_clients(self, seen_at: datetime) -> int:
        """Persist existing success evidence before historical child rows are purged."""
        proof = or_(
            select(MCPOAuthAuthorization.id)
            .where(
                MCPOAuthAuthorization.client_id == MCPOAuthClient.client_id,
                MCPOAuthAuthorization.status.in_(("approved", "consumed")),
            )
            .exists(),
            select(MCPOAuthToken.id).where(MCPOAuthToken.client_id == MCPOAuthClient.client_id).exists(),
        )
        result = await self.db.execute(
            update(MCPOAuthClient)
            .where(MCPOAuthClient.last_seen_at.is_(None), proof)
            .values(last_seen_at=seen_at)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0

    async def delete_stale(self, *, registered_since: datetime, older_than: datetime, limit: int = 500) -> int:
        """Delete proven unused registrations, under parent locks and a fresh recheck.

        Old registrations predating GC are ambiguous and retained. Any child row
        postpones GC, including expired history not yet removed by its own job.
        PostgreSQL READ COMMITTED gives the DELETE its own fresh snapshot.
        """
        if type(limit) is not int or not 1 <= limit <= 500:
            raise ValueError("client GC batch limit must be 1..500")
        if self.db.get_bind().dialect.name == "postgresql":
            isolation = await self.db.scalar(text("SHOW transaction_isolation"))
            if isolation != "read committed":
                raise RuntimeError("client GC requires PostgreSQL READ COMMITTED for its fresh recheck")
        eligible = (
            MCPOAuthClient.registered_at >= registered_since,
            MCPOAuthClient.registered_at < older_than,
            MCPOAuthClient.last_seen_at.is_(None),
            ~select(MCPOAuthAuthorization.id)
            .where(MCPOAuthAuthorization.client_id == MCPOAuthClient.client_id)
            .exists(),
            ~select(MCPOAuthToken.id).where(MCPOAuthToken.client_id == MCPOAuthClient.client_id).exists(),
        )
        result = await self.db.execute(
            select(MCPOAuthClient.id)
            .where(*eligible)
            .order_by(MCPOAuthClient.registered_at, MCPOAuthClient.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        ids = list(result.scalars().all())
        if not ids:
            return 0
        result = await self.db.execute(
            delete(MCPOAuthClient)
            .where(MCPOAuthClient.id.in_(ids), *eligible)
            .execution_options(synchronize_session=False)
        )
        return result.rowcount or 0
