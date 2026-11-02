"""版本记录的写入编排与历史归档替换；数据库是页面唯一读取来源。"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_feedback import ProductUpdate, ProductUpdateStatus
from app.repositories.product_feedback_repo import ProductUpdateRepository
from app.schemas.product_feedback import ProductUpdateCreate, ProductUpdatePatch


async def create_update(db: AsyncSession, data: ProductUpdateCreate, admin_id: int):
    repo = ProductUpdateRepository(db)
    await repo.lock_catalog()
    if await repo.find_by_version(data.version):
        raise HTTPException(409, "这个日期已有更新记录，请编辑现有记录")
    row = ProductUpdate(
        version=data.version,
        title=data.title,
        description=data.summary,
        status=data.status,
        target_date=data.target_date,
        shipped_at=data.shipped_at,
        items=[entry.model_dump(mode="json") for entry in data.items],
        created_by_id=admin_id,
    )
    repo.add_instance(row)
    await db.flush()
    await db.refresh(row)
    return row


async def patch_update(db: AsyncSession, update_id: int, data: ProductUpdatePatch):
    repo = ProductUpdateRepository(db)
    await repo.lock_catalog()
    row = await repo.get_by_id(update_id)
    if row is None:
        raise HTTPException(404, "Product update not found")
    changes = data.model_dump(exclude_unset=True)
    if data.version:
        existing = await repo.find_by_version(data.version)
        if existing is not None and existing.id != row.id:
            raise HTTPException(409, "这个日期已有更新记录，请编辑现有记录")
    for key, value in changes.items():
        if key in ("version", "title", "summary", "items", "status") and value is None:
            raise HTTPException(422, f"{key} cannot be null")
        setattr(row, "description" if key == "summary" else key, value)
    if data.status is not None and data.status != ProductUpdateStatus.shipped and "shipped_at" not in changes:
        row.shipped_at = None
    row.updated_at = datetime.now(UTC)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_update(db: AsyncSession, update_id: int):
    repo = ProductUpdateRepository(db)
    row = await repo.get_by_id(update_id)
    if row is None:
        raise HTTPException(404, "Product update not found")
    await repo.delete_instance(row)


_FIELDS = (
    "id",
    "version",
    "status",
    "target_date",
    "shipped_at",
    "items",
    "created_by_id",
    "created_at",
    "updated_at",
    "title",
    "description",
    "kind",
)


def fingerprint(rows: list[dict]) -> str:
    data = json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode()).hexdigest()


async def snapshot_updates(db: AsyncSession, *, lock: bool = False) -> list[dict]:
    repo = ProductUpdateRepository(db)
    if lock:
        await repo.lock_catalog()
    result = []
    for row in await repo.list_all_for_rebuild():
        item = {}
        for key in _FIELDS:
            value = getattr(row, key)
            if isinstance(value, datetime):
                value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
            item[key] = value.isoformat() if hasattr(value, "isoformat") else value
        result.append(item)
    return result


async def replace_updates(db: AsyncSession, rows: list[dict], *, expected: str, restore: bool = False):
    current = await snapshot_updates(db, lock=True)
    if fingerprint(current) != expected:
        raise ValueError("版本记录已变化，请重新生成计划，不能覆盖期间的新编辑")
    if not restore and not rows:
        raise ValueError("整理稿不能为空")
    prepared = []
    for item in rows:
        if restore:
            payload = {key: item.get(key) for key in _FIELDS}
            for field in ("created_at", "updated_at", "shipped_at"):
                if payload[field]:
                    payload[field] = datetime.fromisoformat(payload[field])
            if payload["target_date"]:
                from datetime import date

                payload["target_date"] = date.fromisoformat(payload["target_date"])
        else:
            checked = ProductUpdateCreate.model_validate(item)
            payload = checked.model_dump(exclude={"summary"})
            payload["description"] = checked.summary
            payload["status"] = checked.status.value
            payload["items"] = [entry.model_dump(mode="json") for entry in checked.items]
        prepared.append(ProductUpdate(**payload))
    if not restore and len({row.version for row in prepared}) != len(prepared):
        raise ValueError("日期版本不能重复")
    await ProductUpdateRepository(db).replace_catalog(prepared)
    return await snapshot_updates(db)
