"""
Category repository — CRUD + seed data helpers.
"""

from __future__ import annotations

import logging
from typing import Optional, Sequence

from sqlalchemy import select, update

from app.models.category import Category
from app.repositories.base import BaseRepository

logger = logging.getLogger(__name__)


class CategoryRepository(BaseRepository[Category]):
    model = Category

    async def get_by_name(self, name: str) -> Optional[Category]:
        """Find a category by exact name (case-insensitive)."""
        stmt = select(Category).where(Category.name == name)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_names(self) -> list[str]:
        """Return all active category names for LLM prompt injection."""
        stmt = select(Category.name).where(Category.is_active.is_(True)).order_by(Category.name)
        result = await self.db.execute(stmt)
        return [row[0] for row in result.all()]

    async def get_all_active(self) -> Sequence[Category]:
        """Return all active categories."""
        stmt = select(Category).where(Category.is_active.is_(True)).order_by(Category.content_count.desc())
        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def get_or_create(
        self,
        name: str,
        description: Optional[str] = None,
        keywords: Optional[str] = None,
        is_auto_created: bool = True,
    ) -> Category:
        """Get existing category or auto-create a new one.

        This is the core method for LLM-driven dynamic classification:
        LLM returns a category name, we either find it or create it.
        """
        # Normalize: strip whitespace
        name = name.strip()

        existing = await self.get_by_name(name)
        if existing:
            return existing

        # Auto-create new category discovered by LLM
        logger.info("Auto-creating new category: %s", name)
        new_cat = await self.create(
            name=name,
            description=description or f"自动发现的分类：{name}",
            keywords=keywords,
            is_auto_created=is_auto_created,
            is_active=True,
            content_count=0,
        )
        return new_cat

    async def increment_count(self, category_name: str) -> None:
        """Increment the denormalized content_count for a category."""
        await self.db.execute(
            update(Category).where(Category.name == category_name).values(content_count=Category.content_count + 1)
        )
        await self.db.flush()
