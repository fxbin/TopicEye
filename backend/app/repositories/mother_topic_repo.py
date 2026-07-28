"""
Repository for MotherTopic model operations.

封装母题的 CRUD 与多租户可见性查询：
- 系统模板（owner_user_id IS NULL）+ 用户 fork 的可见性过滤
- admin 全量查询
- name 同 scope 唯一性校验
- fork 系统模板到用户名下
- 软删除（is_active=False）

多租户模型：
- owner_user_id IS NULL → 系统模板，admin 维护，用户只读
- owner_user_id = <uid>  → 用户私有 fork，用户可自由改/加/停用
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select

from app.models.mother_topic import MotherTopic
from app.repositories._query_helpers import apply_visibility
from app.repositories.base import BaseRepository


class MotherTopicRepository(BaseRepository[MotherTopic]):
    """MotherTopic CRUD + 多租户可见性查询。"""

    model = MotherTopic

    async def list_visible_for_user(
        self,
        *,
        user_id: int,
        active_only: bool = False,
    ) -> Sequence[MotherTopic]:
        """返回当前用户可见的母题（系统模板 + 自己的 fork），按 name 去重。

        按display_order, id 排序。active_only=True 时仅返回 is_active=True 的记录。

        去重规则：如果用户 fork 了某个系统模板（同名），只返回 fork 版本
        （用户可能已自定义关键词/权重），系统模板仅在用户未 fork 时作为 fallback。

        执行顺序：先查全量去重，再按 active_only 过滤。
        这样用户停用自己的 fork 后，去重时选中 fork（inactive），
        系统模板被丢弃，最后 active_only 过滤掉 inactive fork → 话题不再显示。
        """
        stmt = select(MotherTopic).order_by(MotherTopic.display_order, MotherTopic.id)
        stmt = apply_visibility(stmt, MotherTopic, visible_user_id=user_id)
        result = await self.db.execute(stmt)
        all_topics = result.scalars().all()

        # Deduplicate by name: prefer user's fork over system template.
        # User forks (owner_user_id is not None) take priority; system
        # templates (owner_user_id is None) serve as fallback only when
        # the user hasn't forked that name.
        seen_names: set[str] = set()
        deduped: list[MotherTopic] = []
        for topic in all_topics:
            if topic.owner_user_id is not None:
                seen_names.add(topic.name)
                deduped.append(topic)
        for topic in all_topics:
            if topic.owner_user_id is None and topic.name not in seen_names:
                seen_names.add(topic.name)
                deduped.append(topic)

        # Apply active_only filter AFTER dedup, so that a user deactivating
        # their fork also suppresses the system template fallback.
        if active_only:
            deduped = [t for t in deduped if t.is_active]

        # Preserve original (display_order, id) sort order.
        deduped.sort(key=lambda t: (t.display_order, t.id))
        return deduped

    async def list_all_for_admin(self, *, active_only: bool = False) -> Sequence[MotherTopic]:
        """admin 审计用：返回全量母题（含其他用户的私有 fork）。

        按display_order, id 排序。active_only=True 时仅返回 is_active=True 的记录。
        """
        stmt = select(MotherTopic).order_by(MotherTopic.display_order, MotherTopic.id)
        if active_only:
            stmt = stmt.where(MotherTopic.is_active == True)  # noqa: E712
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def find_by_name_in_scope(
        self,
        *,
        name: str,
        owner_user_id: int | None,
    ) -> MotherTopic | None:
        """同 scope 内按 name 查询母题，不存在返回 None。

        - owner_user_id=None 时在系统模板范围内查
        - owner_user_id=<uid> 时在该用户的私有 fork 范围内查

        用于 create/update 时的 name 唯一性校验。
        """
        stmt = select(MotherTopic).where(MotherTopic.name == name)
        if owner_user_id is None:
            stmt = stmt.where(MotherTopic.owner_user_id.is_(None))
        else:
            stmt = stmt.where(MotherTopic.owner_user_id == owner_user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def find_duplicate_name_excluding_id(
        self,
        *,
        name: str,
        owner_user_id: int | None,
        exclude_id: int,
    ) -> MotherTopic | None:
        """同 scope 内按 name 查询母题，排除指定 id。用于 update 时的重名校验。"""
        scope_filter = (
            MotherTopic.owner_user_id.is_(None) if owner_user_id is None
            else MotherTopic.owner_user_id == owner_user_id
        )
        stmt = select(MotherTopic).where(
            MotherTopic.name == name,
            scope_filter,
            MotherTopic.id != exclude_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_system_templates(self) -> Sequence[MotherTopic]:
        """返回全部系统模板（owner_user_id IS NULL），按 display_order 排序。"""
        stmt = (
            select(MotherTopic)
            .where(MotherTopic.owner_user_id.is_(None))
            .order_by(MotherTopic.display_order)
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def list_user_topic_names(self, user_id: int) -> set[str]:
        """返回指定用户已有的母题名集合，用于 fork 时跳过已存在的母题。"""
        stmt = select(MotherTopic.name).where(MotherTopic.owner_user_id == user_id)
        result = await self.db.execute(stmt)
        return {name for (name,) in result.all()}

    def add_instance(self, topic: MotherTopic) -> None:
        """将外部已构造的 MotherTopic 实例加入 session。

        供 create/fork 端点使用：那里由调用方完成字段加工，repo 只负责持久化。
        不 flush/commit，调用方负责事务边界。
        """
        self.db.add(topic)
