"""
Generic Repository base class.

Provides reusable CRUD + paginated listing + filtered queries.
Subclasses only need to set the model class and optional filter mappings.
"""

from __future__ import annotations

import logging
from typing import Any, Generic, Optional, Type, TypeVar
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError

logger = logging.getLogger(__name__)

ModelType = TypeVar("ModelType")


class BaseRepository[ModelType]:
    """
    Base repository with common CRUD operations.

    Usage:
        class ContentRepo(BaseRepository[ContentItem]):
            model = ContentItem

            # Optional: define allowed filter fields
            filter_fields = {"source_type", "platform", "status", "category"}
    """

    model: type[ModelType]

    def __init__(self, db: AsyncSession):
        self.db = db

    # ── Read ────────────────────────────────────────────────────────

    async def get_by_id(self, id: int) -> ModelType | None:
        """Fetch a single record by primary key. Returns None if not found."""
        result = await self.db.execute(select(self.model).where(self.model.id == id))
        return result.scalar_one_or_none()

    async def get_by_id_or_raise(self, id: int, resource_name: str = "") -> ModelType:
        """Fetch by ID or raise NotFoundError."""
        obj = await self.get_by_id(id)
        if obj is None:
            name = resource_name or self.model.__name__
            raise NotFoundError(resource=name, resource_id=id)
        return obj

    async def get_one(self, *filters) -> ModelType | None:
        """Fetch a single record matching filters."""
        stmt = select(self.model)
        for f in filters:
            stmt = stmt.where(f)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    # ── List with pagination + filtering ────────────────────────────

    async def list_paginated(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: dict[str, Any] | None = None,
        sort_by: str = "id",
        sort_order: str = "desc",
    ) -> tuple[Sequence[ModelType], int]:
        """
        Return (items, total_count) with pagination, filtering, and sorting.

        Args:
            page: 1-indexed page number
            page_size: items per page
            filters: dict of {column_name: value} for exact-match WHERE clauses
            sort_by: column name to sort by
            sort_order: 'asc' or 'desc'

        Returns:
            (list_of_items, total_matching_count)
        """
        stmt = select(self.model)
        count_stmt = select(func.count()).select_from(self.model)

        # Apply filters
        if filters:
            for field, value in filters.items():
                if value is None:
                    continue
                col = getattr(self.model, field, None)
                if col is None:
                    continue
                # Support ilike for string fields with % wildcards
                if isinstance(value, str) and ("%" in value or "_" in value):
                    stmt = stmt.where(col.ilike(value))
                    count_stmt = count_stmt.where(col.ilike(value))
                else:
                    stmt = stmt.where(col == value)
                    count_stmt = count_stmt.where(col == value)

        # Count
        total_result = await self.db.execute(count_stmt)
        total = total_result.scalar() or 0

        # Sort
        sort_col = getattr(self.model, sort_by, None)
        if sort_col is not None:
            stmt = stmt.order_by(sort_col.desc() if sort_order == "desc" else sort_col.asc())

        # Paginate
        offset = (page - 1) * page_size
        stmt = stmt.offset(offset).limit(page_size)

        result = await self.db.execute(stmt)
        items = result.scalars().all()

        return items, total

    # ── Create / Update ─────────────────────────────────────────────

    async def create(self, **kwargs) -> ModelType:
        """Create and persist a new record."""
        obj = self.model(**kwargs)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, id: int, **kwargs) -> ModelType:
        """Update fields on an existing record."""
        obj = await self.get_by_id_or_raise(id)
        for key, value in kwargs.items():
            if hasattr(obj, key):
                setattr(obj, key, value)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    # ── Delete ──────────────────────────────────────────────────────

    async def delete(self, id: int) -> None:
        """Delete a record by ID."""
        obj = await self.get_by_id_or_raise(id)
        await self.db.delete(obj)
        await self.db.flush()

    # ── Count ───────────────────────────────────────────────────────

    async def count(self, **filters) -> int:
        """Count records matching filters."""
        stmt = select(func.count()).select_from(self.model)
        for field, value in filters.items():
            col = getattr(self.model, field, None)
            if col is not None and value is not None:
                stmt = stmt.where(col == value)
        result = await self.db.execute(stmt)
        return result.scalar() or 0
