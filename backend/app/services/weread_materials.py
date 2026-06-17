from __future__ import annotations

from datetime import datetime, timezone, UTC
import re
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType
from app.models.user_integration import UserIntegration
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.dedup import build_hash
from app.services.integration_service import WEREAD_PROVIDER
from app.services.source_read_cache import invalidate_source_read_caches

WEREAD_SOURCE_URL = "https://weread.qq.com/r/weread-skills"
WEREAD_SOURCE_NAME = "微信读书素材"
WEREAD_LIST_KEYS = ("items", "data", "books", "notes", "reviews", "highlights")
WEREAD_CONTAINER_KEYS = ("data", "result", "payload")


def _entry_url(entry: dict[str, Any]) -> str:
    value = str(
        entry.get("url")
        or entry.get("book_url")
        or entry.get("bookUrl")
        or entry.get("review_url")
        or entry.get("reviewUrl")
        or WEREAD_SOURCE_URL
    ).strip()
    return value or WEREAD_SOURCE_URL


def redact_weread_sync_error(message: str, api_key: str | None) -> str:
    redacted = str(message)
    stripped_key = (api_key or "").strip()
    secrets = {stripped_key, quote(stripped_key, safe="")} if stripped_key else set()
    for secret in sorted((item for item in secrets if item), key=len, reverse=True):
        redacted = redacted.replace(secret, "***")
    return re.sub(r"Bearer\s+[^\s,;]+", "Bearer ***", redacted, flags=re.IGNORECASE)


def _collect_weread_items(payload: Any, *, depth: int = 0) -> list[Any]:
    if depth > 4:
        return []
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []

    raw_items: list[Any] = []
    visited: set[int] = set()

    def collect(value: Any) -> None:
        value_id = id(value)
        if value_id in visited:
            return
        visited.add(value_id)
        raw_items.extend(_collect_weread_items(value, depth=depth + 1))

    for key in WEREAD_LIST_KEYS:
        value = payload.get(key)
        if isinstance(value, list):
            raw_items.extend(value)
        elif isinstance(value, dict):
            collect(value)

    for key in WEREAD_CONTAINER_KEYS:
        value = payload.get(key)
        if isinstance(value, dict):
            collect(value)

    return raw_items


def normalize_weread_entries(payload: Any) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in _collect_weread_items(payload):
        if not isinstance(raw, dict):
            continue
        title = str(raw.get("title") or raw.get("book_title") or raw.get("bookTitle") or raw.get("name") or "").strip()
        note = str(
            raw.get("note")
            or raw.get("review")
            or raw.get("markText")
            or raw.get("abstract")
            or raw.get("summary")
            or ""
        ).strip()
        if not title and not note:
            continue
        author = raw.get("author") or raw.get("book_author") or raw.get("bookAuthor")
        entries.append(
            {
                "title": title or note[:80],
                "url": _entry_url(raw),
                "author": str(author).strip() if author else None,
                "summary": note[:1000],
                "raw_content": note or title,
                "cover_url": raw.get("cover") or raw.get("cover_url") or raw.get("coverUrl"),
                "published_at": datetime.now(UTC),
            }
        )
    return entries


async def fetch_weread_materials(api_key: str, *, limit: int = 50) -> list[dict[str, Any]]:
    endpoint = str(settings.WEREAD_SKILL_API_URL or "").strip()
    if not endpoint:
        raise RuntimeError("微信读书 Skill API endpoint 未配置，请先接入真实 Skill 服务地址")

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        response = await client.get(
            endpoint,
            headers={"Authorization": f"Bearer {api_key.strip()}"},
            params={"limit": limit},
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = redact_weread_sync_error(response.text, api_key).strip()
            detail = f"微信读书 Skill 返回 {response.status_code}"
            if body:
                detail = f"{detail}: {body[:300]}"
            raise RuntimeError(detail) from exc
        return normalize_weread_entries(response.json())


async def ensure_weread_source(db: AsyncSession) -> Source:
    result = await db.execute(select(Source).where(Source.url == WEREAD_SOURCE_URL))
    source = result.scalar_one_or_none()
    if source:
        return source

    source = Source(
        name=WEREAD_SOURCE_NAME,
        source_type=SourceType.API,
        url=WEREAD_SOURCE_URL,
        platform="微信读书",
        category="阅读素材",
        weight=4,
        status=SourceStatus.ACTIVE,
        enabled=True,
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return source


async def sync_weread_materials(
    db: AsyncSession,
    integration: UserIntegration,
    *,
    api_key: str | None = None,
    limit: int = 50,
) -> dict[str, int | str]:
    if integration.provider != WEREAD_PROVIDER:
        raise ValueError("微信读书 API Key 未配置")
    from app.services.integration_service import integration_api_key

    resolved_api_key = (api_key or integration_api_key(integration) or "").strip()
    if not resolved_api_key:
        raise ValueError("微信读书 API Key 未配置")

    source = await ensure_weread_source(db)
    fetched = new = duplicates = 0
    now = datetime.now(UTC)
    try:
        entries = await fetch_weread_materials(resolved_api_key, limit=limit)
        fetched = len(entries)
        for entry in entries:
            content_hash = build_hash(str(entry.get("title") or "") + str(entry.get("url") or ""))
            exists = await db.scalar(select(ContentItem.id).where(ContentItem.content_hash == content_hash))
            if exists:
                duplicates += 1
                continue
            db.add(
                ContentItem(
                    title=str(entry["title"])[:500],
                    url=str(entry.get("url") or WEREAD_SOURCE_URL)[:1024],
                    source_id=source.id,
                    source_name=source.name,
                    source_type=SourceType.API.value,
                    platform="微信读书",
                    author=entry.get("author"),
                    published_at=entry.get("published_at") or now,
                    content_hash=content_hash,
                    summary=entry.get("summary") or None,
                    raw_content=entry.get("raw_content") or None,
                    cover_url=entry.get("cover_url"),
                    category="阅读素材",
                    tags=["微信读书", "阅读笔记"],
                    status=ContentStatus.PENDING,
                )
            )
            new += 1

        source.last_sync_at = now
        source.status = SourceStatus.ACTIVE
        source.sync_error = None
        integration.last_sync_at = now
        integration.last_sync_status = "success"
        integration.last_sync_error = None
        await db.flush()
        invalidate_source_read_caches()
        if new:
            invalidate_content_read_caches()
            from app.scheduler import _request_post_sync_pipeline

            _request_post_sync_pipeline({"new": new})
        return {
            "fetched": fetched,
            "new": new,
            "duplicates": duplicates,
            "source_name": source.name,
        }
    except Exception as exc:
        message = redact_weread_sync_error(str(exc), resolved_api_key)
        source.last_sync_at = now
        source.status = SourceStatus.ERROR
        source.sync_error = message[:500]
        integration.last_sync_at = now
        integration.last_sync_status = "error"
        integration.last_sync_error = message[:500]
        await db.flush()
        invalidate_source_read_caches()
        raise RuntimeError(message) from exc
