"""Category API endpoints — list and manage content categories."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.repositories.category_repo import CategoryRepository

router = APIRouter(prefix="/categories", tags=["categories"])


@router.get("")
async def list_categories(db: AsyncSession = Depends(get_db)):
    """Return all active categories with content counts."""
    repo = CategoryRepository(db)
    categories = await repo.get_all_active()
    return {
        "categories": [
            {
                "id": c.id,
                "name": c.name,
                "description": c.description,
                "keywords": c.keywords.split(",") if c.keywords else [],
                "is_auto_created": c.is_auto_created,
                "content_count": c.content_count,
            }
            for c in categories
        ]
    }
