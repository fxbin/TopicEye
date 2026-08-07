"""Repository for UserInterestVector — per-user tag preference weights."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.models.user_interest_vector import UserInterestVector
from app.repositories.base import BaseRepository


class InterestVectorRepository(BaseRepository[UserInterestVector]):
    """CRUD + batch operations for user interest vectors."""

    model = UserInterestVector

    async def get_user_vector(self, user_id: int) -> dict[str, float]:
        """Return ``{tag: weight}`` for all tags belonging to *user_id*."""
        result = await self.db.execute(
            select(UserInterestVector.tag, UserInterestVector.weight).where(
                UserInterestVector.user_id == user_id
            )
        )
        return {tag: float(weight) for tag, weight in result.all()}

    async def upsert_tag(
        self,
        user_id: int,
        tag: str,
        weight: float,
        signal_source: str,
    ) -> None:
        """Insert or update a single tag weight (upsert)."""
        tag_lower = tag.lower().strip()
        if not tag_lower:
            return

        stmt = pg_insert(UserInterestVector).values(
            user_id=user_id,
            tag=tag_lower,
            weight=weight,
            signal_source=signal_source,
        )
        stmt = stmt.on_conflict_do_update(
            constraint="uq_user_interest_tag",
            set_={
                "weight": weight,
                "signal_source": signal_source,
            },
        )

        await self.db.execute(stmt)
        await self.db.flush()

    async def bulk_upsert_tags(
        self,
        user_id: int,
        tag_weights: dict[str, tuple[float, str]],
    ) -> None:
        """Batch upsert ``{tag: (weight, signal_source)}`` pairs."""
        if not tag_weights:
            return
        for tag, (weight, signal_source) in tag_weights.items():
            await self.upsert_tag(user_id, tag, weight, signal_source)

    async def delete_user_vector(self, user_id: int) -> int:
        """Remove all interest vector entries for *user_id*. Returns deleted count."""
        result = await self.db.execute(
            delete(UserInterestVector).where(UserInterestVector.user_id == user_id)
        )
        await self.db.flush()
        return result.rowcount or 0

    async def get_top_tags(
        self,
        user_id: int,
        limit: int = 20,
    ) -> Sequence[tuple[str, float]]:
        """Return top-N ``(tag, weight)`` pairs ordered by absolute weight."""
        result = await self.db.execute(
            select(UserInterestVector.tag, UserInterestVector.weight)
            .where(UserInterestVector.user_id == user_id)
            .order_by(UserInterestVector.weight.desc())
            .limit(limit)
        )
        return result.all()
