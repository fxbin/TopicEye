from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, func, select

from app.models.mute_rule import MuteRule
from app.repositories.base import BaseRepository


class MuteRuleRepository(BaseRepository[MuteRule]):
    """用户降噪规则的唯一 ORM 入口（#171）。

    规则永远按 user_id 隔离：list/count/create/delete 都以当前用户为口径，
    不提供跨用户查询（全局静音不做，见设计决定）。
    """

    model = MuteRule

    async def list_for_user(self, user_id: int) -> Sequence[MuteRule]:
        stmt = (
            select(MuteRule).where(MuteRule.user_id == user_id).order_by(MuteRule.created_at.desc(), MuteRule.id.desc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def count_for_user(self, user_id: int, rule_type: str) -> int:
        stmt = (
            select(func.count())
            .select_from(MuteRule)
            .where(MuteRule.user_id == user_id, MuteRule.rule_type == rule_type)
        )
        result = await self.db.execute(stmt)
        return int(result.scalar() or 0)

    async def get_by_value(self, user_id: int, rule_type: str, value: str) -> MuteRule | None:
        stmt = select(MuteRule).where(
            MuteRule.user_id == user_id,
            MuteRule.rule_type == rule_type,
            MuteRule.value == value,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create_rule(self, user_id: int, rule_type: str, value: str) -> MuteRule:
        obj = MuteRule(user_id=user_id, rule_type=rule_type, value=value)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete_for_user(self, user_id: int, rule_id: int) -> bool:
        stmt = delete(MuteRule).where(MuteRule.id == rule_id, MuteRule.user_id == user_id)
        result = await self.db.execute(stmt)
        await self.db.flush()
        return result.rowcount > 0
