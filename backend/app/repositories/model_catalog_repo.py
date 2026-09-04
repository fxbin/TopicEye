"""Repository for ModelCatalogModel operations.

模型目录（models.dev 缓存）的唯一 ORM 入口：
- 批量 upsert（PG / SQLite 双方言 on-conflict，供每日刷新与快照 seed 复用）
- 按provider / 搜索词列模型（管理端表单数据源）
- provider 维度统计（精选清单 model_count）
- 陈旧行清理（全量刷新成功后删除本次未命中的行）

不写业务逻辑：刷新编排、精选清单、payload 组装在 service 层。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import delete, func, or_, select

from app.models.model_catalog import ModelCatalogModel
from app.repositories.base import BaseRepository

_UPSERT_CHUNK_SIZE = 500

# upsert 时冲突更新覆盖的列（不含 provider/model_id 冲突键与 id/fetched_at 由语句单独处理）
_UPSERT_UPDATE_COLUMNS = (
    "name",
    "context_window",
    "max_output_tokens",
    "cost_per_1m_input",
    "cost_per_1m_output",
    "cost_per_1m_cache_read",
    "supports_tool_call",
    "supports_structured_output",
    "supports_reasoning",
    "input_modalities",
    "output_modalities",
    "open_weights",
    "status",
    "release_date",
    "last_updated",
)


class ModelCatalogRepository(BaseRepository[ModelCatalogModel]):
    """ModelCatalogModel 缓存表 CRUD 与查询封装。"""

    model = ModelCatalogModel

    def _dialect_insert(self, rows: list[dict]):
        """按当前 session 方言选择支持 on-conflict 的 insert 构造（PG / SQLite）。"""
        dialect_name = self.db.get_bind().dialect.name
        if dialect_name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert

            return pg_insert(ModelCatalogModel).values(rows)
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert

        return sqlite_insert(ModelCatalogModel).values(rows)

    async def upsert_entries(self, entries: list[dict], *, fetched_at: datetime) -> int:
        """批量 upsert 目录条目，返回处理行数。

        entries 的 key 需与 ModelCatalogModel 列名一致（由 service 的解析器保证）。
        fetched_at 会同时注入插入值与冲突更新分支——新插入行不能依赖列默认值，
        否则调用方指定的批次时间会被插入时刻覆盖，陈旧清理将失配。
        不 commit——事务边界在调用方（刷新 job / seed step）。
        """
        total = 0
        for start in range(0, len(entries), _UPSERT_CHUNK_SIZE):
            chunk = entries[start : start + _UPSERT_CHUNK_SIZE]
            if not chunk:
                continue
            rows = [{**entry, "fetched_at": fetched_at} for entry in chunk]
            stmt = self._dialect_insert(rows)
            update_map = {column: stmt.excluded[column] for column in _UPSERT_UPDATE_COLUMNS}
            update_map["fetched_at"] = stmt.excluded["fetched_at"]
            stmt = stmt.on_conflict_do_update(index_elements=["provider", "model_id"], set_=update_map)
            await self.db.execute(stmt)
            total += len(chunk)
        return total

    async def delete_stale(self, *, fetched_before: datetime) -> int:
        """删除 fetched_at 早于批次时间的行（全量刷新成功后清理已下架模型）。"""
        stmt = delete(ModelCatalogModel).where(ModelCatalogModel.fetched_at < fetched_before)
        result = await self.db.execute(stmt)
        return result.rowcount or 0

    async def list_models(
        self,
        *,
        provider: str | None = None,
        search: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[Sequence[ModelCatalogModel], int]:
        """按 provider 精确匹配 + model_id/name 搜索列模型，返回 (items, total)。"""
        conditions = []
        if provider:
            conditions.append(ModelCatalogModel.provider == provider)
        if search:
            pattern = f"%{search.strip()}%"
            conditions.append(or_(ModelCatalogModel.model_id.ilike(pattern), ModelCatalogModel.name.ilike(pattern)))
        base = select(ModelCatalogModel)
        count_stmt = select(func.count()).select_from(ModelCatalogModel)
        for condition in conditions:
            base = base.where(condition)
            count_stmt = count_stmt.where(condition)
        total = (await self.db.execute(count_stmt)).scalar() or 0
        result = await self.db.execute(
            base.order_by(ModelCatalogModel.provider, ModelCatalogModel.model_id).offset(offset).limit(limit)
        )
        return result.scalars().all(), total

    async def get_model(self, provider: str, model_id: str) -> ModelCatalogModel | None:
        stmt = select(ModelCatalogModel).where(
            ModelCatalogModel.provider == provider,
            ModelCatalogModel.model_id == model_id,
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def list_provider_stats(self) -> dict[str, int]:
        """provider → 模型数统计，用于精选清单与“全部 provider”列表。"""
        stmt = (
            select(ModelCatalogModel.provider, func.count())
            .group_by(ModelCatalogModel.provider)
            .order_by(func.count().desc())
        )
        result = await self.db.execute(stmt)
        return dict(result.all())

    async def count_all(self) -> int:
        return (await self.db.execute(select(func.count()).select_from(ModelCatalogModel))).scalar() or 0

    async def latest_fetched_at(self) -> datetime | None:
        return (await self.db.execute(select(func.max(ModelCatalogModel.fetched_at)))).scalar()
