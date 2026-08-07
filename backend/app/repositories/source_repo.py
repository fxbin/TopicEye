"""
Repository for Source model operations.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.source import Source, SourceStatus
from app.repositories.base import BaseRepository


class SourceRepository(BaseRepository[Source]):
    """Source table CRUD + enabled-sources query."""

    model = Source

    async def get_enabled_sources(self) -> Sequence[Source]:
        """Return syncable sources in the user-managed order.

        Excludes hidden sources (e.g. WeRead auto-created virtual source)
        that are synced via their own integration path, not the batch scraper.
        """
        stmt = (
            select(Source)
            .where(
                Source.enabled.is_(True),
                Source.status != SourceStatus.DISABLED,
                Source.hidden.is_(False),
            )
            .order_by(Source.sort_order.asc(), Source.id.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def claim_sync(
        self,
        source_id: int,
        *,
        lease_seconds: int,
        min_interval_seconds: int = 0,
    ) -> Source | None:
        """Claim one source for sync, returning None when another run owns it."""
        return await claim_source_sync(
            self.db,
            source_id,
            lease_seconds=lease_seconds,
            min_interval_seconds=min_interval_seconds,
        )

    async def get_max_sort_order(self) -> int | None:
        """返回当前最大 sort_order，无数据返回 None。

        供 create_source / create_my_source / import_source_batch 计算下一 sort_order 使用。
        """
        result = await self.db.execute(select(func.max(Source.sort_order)))
        return result.scalar()

    async def count_user_owned(self, user_id: int) -> int:
        """统计用户私有信源数量，供私有信源配额检查使用。

        排除 hidden=True 的系统自动创建信源（如微信读书虚拟信源），
        因为它们不是用户创建的，不应占用用户的私有信源配额。
        """
        result = await self.db.execute(
            select(func.count())
            .select_from(Source)
            .where(
                Source.owner_user_id == user_id,
                Source.hidden.is_(False),
            )
        )
        return result.scalar() or 0

    async def list_public_with_filters(
        self,
        *,
        source_type: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Source], int]:
        """公开信源（scope='system'）分页查询，返回 (items, total)。

        keyword 模糊匹配 name/url/platform/category/keyword 字段（OR ILIKE）。
        排序：sort_order ASC。与 list_sources 端点历史行为等价。
        """
        stmt = select(Source).where(Source.scope == "system")
        count_stmt = select(func.count()).select_from(Source).where(Source.scope == "system")
        filters = []
        if source_type is not None:
            filters.append(Source.source_type == source_type)
        if status is not None:
            filters.append(Source.status == status)
        if enabled is not None:
            filters.append(Source.enabled == enabled)
        cleaned_keyword = keyword.strip() if keyword else ""
        if cleaned_keyword:
            pattern = f"%{cleaned_keyword}%"
            filters.append(
                or_(
                    Source.name.ilike(pattern),
                    Source.url.ilike(pattern),
                    Source.platform.ilike(pattern),
                    Source.category.ilike(pattern),
                    Source.keyword.ilike(pattern),
                )
            )
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)
        total = int(await self.db.scalar(count_stmt) or 0)
        stmt = stmt.order_by(Source.sort_order.asc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def list_user_owned_with_filters(
        self,
        user_id: int,
        *,
        source_type: str | None = None,
        status: str | None = None,
        enabled: bool | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[Sequence[Source], int]:
        """用户私有信源（owner_user_id=user_id）分页查询，返回 (items, total)。

        排除 hidden=True 的系统自动创建信源（如微信读书虚拟信源）。

        keyword 模糊匹配 name/url/platform/category/keyword 字段（OR ILIKE）。
        排序：sort_order ASC。与 list_my_sources 端点历史行为等价。
        """
        stmt = select(Source).where(
            Source.owner_user_id == user_id,
            Source.hidden.is_(False),
        )
        count_stmt = (
            select(func.count())
            .select_from(Source)
            .where(
                Source.owner_user_id == user_id,
                Source.hidden.is_(False),
            )
        )
        filters = []
        if source_type is not None:
            filters.append(Source.source_type == source_type)
        if status is not None:
            filters.append(Source.status == status)
        if enabled is not None:
            filters.append(Source.enabled == enabled)
        cleaned_keyword = keyword.strip() if keyword else ""
        if cleaned_keyword:
            pattern = f"%{cleaned_keyword}%"
            filters.append(
                or_(
                    Source.name.ilike(pattern),
                    Source.url.ilike(pattern),
                    Source.platform.ilike(pattern),
                    Source.category.ilike(pattern),
                    Source.keyword.ilike(pattern),
                )
            )
        for f in filters:
            stmt = stmt.where(f)
            count_stmt = count_stmt.where(f)
        total = int(await self.db.scalar(count_stmt) or 0)
        stmt = stmt.order_by(Source.sort_order.asc()).offset((page - 1) * page_size).limit(page_size)
        result = await self.db.execute(stmt)
        return result.scalars().all(), total

    async def list_by_ids_and_scope(
        self,
        ids: list[int],
        scope: str,
    ) -> Sequence[Source]:
        """按 id 列表 + scope 查询，供 reorder_sources 端点使用。

        不分页，返回所有匹配的记录。排序按 sort_order ASC。
        """
        if not ids:
            return []
        stmt = (
            select(Source)
            .where(Source.id.in_(ids), Source.scope == scope)
            .order_by(Source.sort_order.asc())
        )
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def find_existing_urls(self, urls: list[str]) -> set[str]:
        """检查给定 URL 列表中已存在的 URL 集合，供批量导入预览使用。"""
        if not urls:
            return set()
        result = await self.db.execute(select(Source.url).where(Source.url.in_(urls)))
        return set(result.scalars().all())


async def claim_source_sync(
    db: AsyncSession,
    source_id: int,
    *,
    lease_seconds: int,
    min_interval_seconds: int = 0,
) -> Source | None:
    """Acquire a cross-process source-sync lease via ``last_sync_at``."""
    now = datetime.now(UTC)
    lease_cutoff = now - timedelta(seconds=max(int(lease_seconds), 1))
    interval_cutoff = now - timedelta(seconds=max(int(min_interval_seconds), 0))

    async def _claim() -> Source | None:
        result = await db.execute(select(Source).where(Source.id == source_id).with_for_update())
        source = result.scalar_one_or_none()
        if source is None:
            return None
        if not source.enabled or source.status == SourceStatus.DISABLED:
            return None
        # DB (SQLite) 读出 last_sync_at 可能是 naive, 统一 aware UTC 再比较
        from app.core.db_backend import ensure_aware_utc

        last_sync_aware = ensure_aware_utc(source.last_sync_at)
        if source.status == SourceStatus.SYNCING and last_sync_aware is not None and last_sync_aware > lease_cutoff:
            return None
        if min_interval_seconds > 0 and last_sync_aware is not None and last_sync_aware > interval_cutoff:
            return None

        source.last_sync_at = now
        source.status = SourceStatus.SYNCING
        source.sync_error = None
        source.updated_at = now
        await db.flush()
        return source

    return await _claim()
