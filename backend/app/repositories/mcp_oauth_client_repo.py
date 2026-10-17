"""Repository for MCPOAuthClient — DCR 注册的 MCP OAuth 客户端查询。

只做查询与落库；secret 加解密在 service（secret_store），事务由调用方负责。
"""

from __future__ import annotations

from sqlalchemy import select

from app.models.mcp_oauth import MCPOAuthClient
from app.repositories.base import BaseRepository


class MCPOAuthClientRepository(BaseRepository[MCPOAuthClient]):
    """MCPOAuthClient CRUD。"""

    model = MCPOAuthClient

    async def get_by_client_id(self, client_id: str) -> MCPOAuthClient | None:
        result = await self.db.execute(select(MCPOAuthClient).where(MCPOAuthClient.client_id == client_id))
        return result.scalar_one_or_none()
