"""Repository for MCPOAuthAuthorization — 授权请求 / 授权码生命周期查询。

状态机由 service 驱动；本层提供查询与两个原子状态迁移（approve / consume），
条件 UPDATE 的 rowcount 保证 pending→approved、approved→consumed 在并发
（双开标签页各点一次授权、授权码被并发兑换）下各只有一路成功。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select, update

from app.models.mcp_oauth import MCPOAuthAuthorization
from app.repositories.base import BaseRepository


class MCPOAuthAuthorizationRepository(BaseRepository[MCPOAuthAuthorization]):
    """MCPOAuthAuthorization CRUD + 原子状态迁移。"""

    model = MCPOAuthAuthorization

    async def get_by_request_id(self, request_id: str) -> MCPOAuthAuthorization | None:
        result = await self.db.execute(
            select(MCPOAuthAuthorization).where(MCPOAuthAuthorization.request_id == request_id)
        )
        return result.scalar_one_or_none()

    async def get_by_code_hash(self, code_hash: str) -> MCPOAuthAuthorization | None:
        result = await self.db.execute(
            select(MCPOAuthAuthorization).where(MCPOAuthAuthorization.code_hash == code_hash)
        )
        return result.scalar_one_or_none()

    async def transition_to_approved(
        self, request_id: str, *, code_hash: str, user_id: int, expires_at: datetime
    ) -> bool:
        """pending → approved 的原子迁移（盖 code_hash、绑用户）；False=已非 pending。"""
        result = await self.db.execute(
            update(MCPOAuthAuthorization)
            .where(MCPOAuthAuthorization.request_id == request_id, MCPOAuthAuthorization.status == "pending")
            .values(
                status="approved",
                code_hash=code_hash,
                user_id=user_id,
                expires_at=expires_at,
                updated_at=datetime.now(UTC),
            )
        )
        return bool(result.rowcount)

    async def consume(self, request_id: str) -> bool:
        """approved → consumed 的原子迁移；返回 False 表示已被消费/非 approved。"""
        result = await self.db.execute(
            update(MCPOAuthAuthorization)
            .where(MCPOAuthAuthorization.request_id == request_id, MCPOAuthAuthorization.status == "approved")
            .values(status="consumed", updated_at=datetime.now(UTC))
        )
        return bool(result.rowcount)

    async def delete_stale(self, older_than: datetime) -> int:
        """清理终态行（consumed/denied 超过保留期）与已过期的未决行，返回删除数。"""
        result = await self.db.execute(
            delete(MCPOAuthAuthorization).where(
                (
                    (MCPOAuthAuthorization.status.in_(("consumed", "denied")))
                    & (MCPOAuthAuthorization.updated_at < older_than)
                )
                | (MCPOAuthAuthorization.expires_at < older_than)
            )
        )
        return result.rowcount or 0
