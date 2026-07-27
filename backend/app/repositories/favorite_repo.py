from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.content import ContentItem
from app.models.favorite import FavoriteItem, FavoriteStatus, FavoriteTargetType
from app.schemas.favorite import FavoriteCreate, FavoriteUpdate


class FavoriteRepo:
    def __init__(self, db: AsyncSession, user_id: int):
        self.db = db
        self.user_id = user_id

    @staticmethod
    def make_target_key(
        target_type: FavoriteTargetType | str,
        *,
        target_id: int | None = None,
        target_key: str | None = None,
    ) -> str:
        if target_key:
            return target_key
        if target_id is None:
            raise ValueError("target_id or target_key is required")
        return str(target_id)

    async def get_by_target(
        self,
        target_type: FavoriteTargetType | str,
        target_key: str,
    ) -> FavoriteItem | None:
        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.target_type == target_type,
                FavoriteItem.target_key == target_key,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(self, data: FavoriteCreate) -> FavoriteItem:
        explicit_fields = data.model_fields_set
        target_key = self.make_target_key(
            data.target_type,
            target_id=data.target_id,
            target_key=data.target_key,
        )
        payload = data.model_dump()
        payload["target_key"] = target_key
        payload["user_id"] = self.user_id

        if data.target_type == FavoriteTargetType.CONTENT:
            payload = await self._merge_content_snapshot(payload)

        if not payload.get("title"):
            raise ValueError("title is required when target cannot be resolved")

        existing = await self.get_by_target(data.target_type, target_key)
        if existing:
            if "status" not in explicit_fields:
                payload.pop("status", None)
            elif payload.get("status") and payload["status"] != existing.status:
                existing.position = await self.next_position_for_status(payload["status"])
            for key, value in payload.items():
                if value is not None and hasattr(existing, key):
                    setattr(existing, key, value)
            existing.updated_at = datetime.now(UTC)
            await self.db.flush()
            await self.db.refresh(existing)
            await self._sync_content_flag(existing, True)
            return existing

        payload["position"] = await self.next_position_for_status(payload.get("status") or FavoriteStatus.INBOX)
        item = FavoriteItem(**payload)
        self.db.add(item)
        await self.db.flush()
        await self.db.refresh(item)
        await self._sync_content_flag(item, True)
        return item

    async def create_from_content(self, content_id: int) -> FavoriteItem:
        data = FavoriteCreate(target_type=FavoriteTargetType.CONTENT, target_id=content_id)
        return await self.upsert(data)

    async def remove_by_content(self, content_id: int) -> bool:
        return await self.delete_by_target(
            FavoriteTargetType.CONTENT,
            self.make_target_key(FavoriteTargetType.CONTENT, target_id=content_id),
        )

    async def delete_by_target(self, target_type: FavoriteTargetType | str, target_key: str) -> bool:
        existing = await self.get_by_target(target_type, target_key)
        result = await self.db.execute(
            delete(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.target_type == target_type,
                FavoriteItem.target_key == target_key,
            )
        )
        if existing:
            await self._sync_content_flag(existing, False)
        await self.db.flush()
        return bool(result.rowcount)

    async def delete(self, favorite_id: int) -> bool:
        item = await self.get_by_id(favorite_id)
        result = await self.db.execute(
            delete(FavoriteItem).where(
                FavoriteItem.id == favorite_id,
                FavoriteItem.user_id == self.user_id,
            )
        )
        if item:
            await self._sync_content_flag(item, False)
        await self.db.flush()
        return bool(result.rowcount)

    async def bulk_delete(self, ids: list[int]) -> int:
        if not ids:
            return 0

        unique_ids = list(dict.fromkeys(ids))
        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id.in_(unique_ids),
            )
        )
        items = list(result.scalars().all())
        by_id = {item.id: item for item in items}

        missing_ids = [item_id for item_id in unique_ids if item_id not in by_id]
        if missing_ids:
            raise LookupError(f"Favorite not found: {missing_ids[0]}")

        for item in items:
            await self._sync_content_flag(item, False)

        deleted = await self.db.execute(
            delete(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id.in_(unique_ids),
            )
        )
        await self.db.flush()
        return int(deleted.rowcount or 0)

    async def update(self, favorite_id: int, data: FavoriteUpdate) -> FavoriteItem | None:
        item = await self.get_by_id(favorite_id)
        if not item:
            return None
        original_status = item.status
        payload = data.model_dump(exclude_unset=True)
        for key, value in payload.items():
            if hasattr(item, key):
                setattr(item, key, value)
        if payload.get("status") and payload["status"] != original_status:
            item.position = await self.next_position_for_status(payload["status"])
        item.updated_at = datetime.now(UTC)
        await self.db.flush()
        await self.db.refresh(item)
        return item

    async def get_by_id(self, favorite_id: int) -> FavoriteItem | None:
        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id == favorite_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        page: int = 1,
        page_size: int = 20,
        target_type: FavoriteTargetType | None = None,
        status: FavoriteStatus | None = None,
        keyword: str | None = None,
    ) -> tuple[Sequence[FavoriteItem], int]:
        stmt = select(FavoriteItem).where(FavoriteItem.user_id == self.user_id)
        count_stmt = select(func.count()).select_from(FavoriteItem).where(FavoriteItem.user_id == self.user_id)

        if target_type:
            stmt = stmt.where(FavoriteItem.target_type == target_type)
            count_stmt = count_stmt.where(FavoriteItem.target_type == target_type)
        if status:
            stmt = stmt.where(FavoriteItem.status == status)
            count_stmt = count_stmt.where(FavoriteItem.status == status)
        if keyword:
            pattern = f"%{keyword}%"
            keyword_filter = or_(
                FavoriteItem.title.ilike(pattern),
                FavoriteItem.note.ilike(pattern),
                FavoriteItem.source_name.ilike(pattern),
                FavoriteItem.target_key.ilike(pattern),
            )
            stmt = stmt.where(keyword_filter)
            count_stmt = count_stmt.where(keyword_filter)

        total_result = await self.db.execute(count_stmt)
        total = int(total_result.scalar() or 0)

        result = await self.db.execute(
            stmt.order_by(
                FavoriteItem.status.asc(),
                FavoriteItem.position.asc(),
                FavoriteItem.updated_at.desc(),
                FavoriteItem.id.desc(),
            )
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return result.scalars().all(), total

    async def next_position_for_status(self, status: FavoriteStatus | str) -> int:
        result = await self.db.execute(
            select(func.min(FavoriteItem.position))
            .where(FavoriteItem.status == status)
            .where(FavoriteItem.user_id == self.user_id)
        )
        current_min = result.scalar()
        if current_min is None:
            return 1000
        return min(int(current_min) - 1000, -1000)

    async def reorder_status(
        self,
        *,
        status: FavoriteStatus,
        ordered_ids: list[int],
    ) -> list[FavoriteItem]:
        return await self._normalize_status_order(status=status, leading_ids=ordered_ids)

    async def bulk_update_status(
        self,
        *,
        status: FavoriteStatus,
        ids: list[int],
    ) -> list[FavoriteItem]:
        return await self._normalize_status_order(status=status, leading_ids=ids)

    async def reorder_board(
        self,
        columns: Sequence[tuple[FavoriteStatus, list[int]]],
    ) -> list[FavoriteItem]:
        ordered_ids = [item_id for _, column_ids in columns for item_id in column_ids]
        if not ordered_ids:
            return []

        unique_ids = list(dict.fromkeys(ordered_ids))
        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id.in_(unique_ids),
            )
        )
        items = list(result.scalars().all())
        by_id = {item.id: item for item in items}

        missing_ids = [item_id for item_id in unique_ids if item_id not in by_id]
        if missing_ids:
            raise LookupError(f"Favorite not found: {missing_ids[0]}")

        now = datetime.now(UTC)
        updated: list[FavoriteItem] = []
        for status, column_ids in columns:
            for index, item_id in enumerate(column_ids):
                item = by_id[item_id]
                item.status = status
                item.position = (index + 1) * 1000
                item.updated_at = now
                updated.append(item)

        await self.db.flush()
        return updated

    async def _normalize_status_order(
        self,
        *,
        status: FavoriteStatus,
        leading_ids: list[int],
    ) -> list[FavoriteItem]:
        if not leading_ids:
            return []

        unique_ids = list(dict.fromkeys(leading_ids))
        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id.in_(unique_ids),
            )
        )
        items = list(result.scalars().all())
        by_id = {item.id: item for item in items}

        missing_ids = [item_id for item_id in unique_ids if item_id not in by_id]
        if missing_ids:
            raise LookupError(f"Favorite not found: {missing_ids[0]}")

        tail_result = await self.db.execute(
            select(FavoriteItem)
            .where(
                FavoriteItem.status == status,
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.id.notin_(unique_ids),
            )
            .order_by(
                FavoriteItem.position.asc(),
                FavoriteItem.updated_at.desc(),
                FavoriteItem.id.desc(),
            )
        )
        tail_items = list(tail_result.scalars().all())
        ordered_items = [by_id[item_id] for item_id in unique_ids] + tail_items

        now = datetime.now(UTC)
        for index, item in enumerate(ordered_items):
            item.status = status
            item.position = (index + 1) * 1000
            item.updated_at = now

        await self.db.flush()
        return ordered_items

    async def state_for_targets(
        self,
        target_type: FavoriteTargetType,
        *,
        target_ids: list[int] | None = None,
        target_keys: list[str] | None = None,
    ) -> list[dict]:
        keys = list(target_keys or [])
        keys.extend(self.make_target_key(target_type, target_id=target_id) for target_id in target_ids or [])
        keys = list(dict.fromkeys(keys))
        if not keys:
            return []

        result = await self.db.execute(
            select(FavoriteItem).where(
                FavoriteItem.user_id == self.user_id,
                FavoriteItem.target_type == target_type,
                FavoriteItem.target_key.in_(keys),
            )
        )
        by_key = {item.target_key: item for item in result.scalars().all()}
        return [
            {
                "target_key": key,
                "is_favorited": key in by_key,
                "favorite_id": by_key[key].id if key in by_key else None,
            }
            for key in keys
        ]

    async def _sync_content_flag(self, item: FavoriteItem, is_favorited: bool) -> None:
        if item.target_type != FavoriteTargetType.CONTENT or item.target_id is None:
            return
        if not is_favorited:
            result = await self.db.execute(
                select(func.count())
                .select_from(FavoriteItem)
                .where(
                    FavoriteItem.target_type == FavoriteTargetType.CONTENT,
                    FavoriteItem.target_key == item.target_key,
                    FavoriteItem.user_id != self.user_id,
                )
            )
            is_favorited = int(result.scalar() or 0) > 0
        await self.db.execute(
            update(ContentItem)
            .where(ContentItem.id == item.target_id)
            .values(is_favorited=is_favorited, updated_at=datetime.now(UTC))
        )

    async def _merge_content_snapshot(self, payload: dict) -> dict:
        content_id = payload.get("target_id")
        if content_id is None:
            return payload

        result = await self.db.execute(select(ContentItem).where(ContentItem.id == content_id))
        content = result.scalar_one_or_none()
        if not content:
            raise LookupError("Content not found")

        if not payload.get("title"):
            payload["title"] = content.title
        if not payload.get("url"):
            payload["url"] = content.url
        if not payload.get("cover_url"):
            payload["cover_url"] = content.cover_url
        if not payload.get("source_name"):
            payload["source_name"] = content.source_name
        if not payload.get("snapshot"):
            payload["snapshot"] = {
                "content_id": content.id,
                "category": content.category,
                "source_type": content.source_type,
                "platform": content.platform,
                "author": content.author,
                "published_at": content.published_at.isoformat() if content.published_at else None,
                "crawled_at": content.crawled_at.isoformat() if content.crawled_at else None,
                "summary": content.summary,
            }
        return payload
