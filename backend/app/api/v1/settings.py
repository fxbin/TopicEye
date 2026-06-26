"""
App-level settings API — RSSHub instance management.
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone, UTC
from urllib.parse import urlsplit, urlunsplit

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import get_current_admin_user
from app.core.database import database_profile, get_db
from app.core.db_backend import database_diagnostics, redact_database_secrets
from app.models.app_setting import AppSetting

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(get_current_admin_user)])

logger = logging.getLogger(__name__)


class RSSHubInstanceItem(BaseModel):
    url: str
    enabled: bool = True
    priority: int = 0
    note: str = ""


class RSSHubInstancesGetResponse(BaseModel):
    instances: list[RSSHubInstanceItem]
    default_instances: list[str]


class RSSHubInstancesUpdateRequest(BaseModel):
    instances: list[RSSHubInstanceItem]


def normalize_rsshub_instance_url(value: str) -> str:
    url = value.strip()
    parts = urlsplit(url)
    scheme = parts.scheme.lower()
    if scheme not in {"http", "https"} or not parts.netloc:
        raise ValueError(f"Invalid URL: {value}")
    netloc = parts.netloc.lower()
    path = parts.path.rstrip("/")
    return urlunsplit((scheme, netloc, path, "", ""))


@router.get("/rsshub/instances", response_model=RSSHubInstancesGetResponse)
async def get_rsshub_instances(db: AsyncSession = Depends(get_db)):
    """Get current RSSHub instance list (from DB or defaults)."""
    result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
    row = result.scalar_one_or_none()

    if row and row.value:
        try:
            raw = json.loads(row.value)
            instances = [RSSHubInstanceItem(**item) for item in raw]
        except json.JSONDecodeError:
            # 存储的 JSON 损坏：当作未配置，但不吞掉 DB/未知异常
            instances = []
        except Exception:
            logger.exception("Failed to parse rsshub_instances setting")
            raise
    else:
        instances = []

    from app.models.app_setting import DEFAULT_RSSHUB_INSTANCES

    return {
        "instances": instances,
        "default_instances": [i["url"] for i in DEFAULT_RSSHUB_INSTANCES],
    }


@router.put("/rsshub/instances")
async def update_rsshub_instances(
    req: RSSHubInstancesUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update RSSHub instance list. Supports enable/disable/add/remove."""
    normalized_instances = []
    seen_urls: set[str] = set()
    for inst in req.instances:
        try:
            url = normalize_rsshub_instance_url(inst.url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        if url in seen_urls:
            raise HTTPException(status_code=409, detail=f"RSSHub instance already exists: {url}")
        seen_urls.add(url)
        normalized_instances.append(inst.model_copy(update={"url": url}))

    raw_value = json.dumps([inst.model_dump() for inst in normalized_instances], ensure_ascii=False)

    result = await db.execute(select(AppSetting).where(AppSetting.key == "rsshub_instances"))
    existing = result.scalar_one_or_none()

    if existing:
        existing.value = raw_value
        existing.updated_at = datetime.now(UTC)
    else:
        db.add(
            AppSetting(
                key="rsshub_instances",
                value=raw_value,
                description="RSSHub 实例列表，支持多实例降级",
                updated_at=datetime.now(UTC),
            )
        )

    await db.commit()

    return {"instances": normalized_instances, "updated": True}


# ── DuckDB analytics layer management ──


@router.get("/duckdb/status")
async def duckdb_status():
    """Get DuckDB analytical layer status.

    DuckDB runs in memory and attaches the configured OLTP database read-only.
    No sync step is needed; analytics reads current OLTP data directly.
    """
    try:
        from app.services.duckdb_service import get_analytics

        analytics = get_analytics()
        status = analytics.status()
        available = status["available"]
        diagnostics = database_diagnostics(database_profile)
        return {
            **status,
            "status": "ok" if available else "unavailable",
            "database": diagnostics,
            "architecture": "in-memory DuckDB + OLTP ATTACH (READ_ONLY)",
            "note": "No sync needed; DuckDB reads the configured OLTP backend directly."
            if available
            else "DuckDB package or required extension is unavailable. Analytical read APIs will return 503 until DuckDB is available.",
        }
    except Exception as e:
        return {
            "status": "error",
            "error": redact_database_secrets(str(e), database_profile),
        }
