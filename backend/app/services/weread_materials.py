from __future__ import annotations

import asyncio
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
        # gateway /user/notebooks 回包：每项含 bookId + book{title,author,cover} + noteCount/reviewCount
        book = raw.get("book") if isinstance(raw.get("book"), dict) else {}
        title = str(
            book.get("title")
            or raw.get("title")
            or raw.get("book_title")
            or raw.get("bookTitle")
            or raw.get("name")
            or ""
        ).strip()
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
        author = book.get("author") or raw.get("author") or raw.get("book_author") or raw.get("bookAuthor")
        # 构造可读的摘要：有笔记/划线数时拼一句统计
        note_count = raw.get("noteCount")
        review_count = raw.get("reviewCount")
        progress = raw.get("readingProgress")
        summary_parts: list[str] = []
        if note:
            summary_parts.append(note[:800])
        if isinstance(note_count, int) and note_count > 0:
            summary_parts.append(f"{note_count} 条划线")
        if isinstance(review_count, int) and review_count > 0:
            summary_parts.append(f"{review_count} 条想法")
        if isinstance(progress, (int, float)) and progress:
            summary_parts.append(f"阅读进度 {int(progress)}%")
        summary = "，".join(summary_parts) if summary_parts else None
        # WeRead Gateway 返回的 sort 字段是最近笔记活动时间戳（Unix seconds），
        # 用作 published_at 以保留微信读书自身的排序顺序。
        sort_value = raw.get("sort")
        if isinstance(sort_value, (int, float)) and sort_value > 1_000_000_000:
            published_at = datetime.fromtimestamp(int(sort_value), tz=UTC)
        else:
            published_at = datetime.now(UTC)
        entries.append(
            {
                "title": title or note[:80],
                "url": _entry_url(raw),
                "author": str(author).strip() if author else None,
                "summary": summary,
                "raw_content": note or title,
                "cover_url": book.get("cover") or raw.get("cover") or raw.get("cover_url") or raw.get("coverUrl"),
                "published_at": published_at,
            }
        )
    return entries


WEREAD_GATEWAY_URL = "https://i.weread.qq.com/api/agent/gateway"
WEREAD_SKILL_VERSION = "1.0.4"
WEREAD_FETCH_BATCH_SIZE = 50
WEREAD_FETCH_MAX_PAGES = 100  # 安全上限：100 页 × 50 条/页 = 5000 条


async def fetch_weread_materials(api_key: str, *, limit: int = 0) -> list[dict[str, Any]]:
    """直连微信读书 Agent Gateway 拉取用户的笔记/划线素材。

    不再依赖外部中间层（WEREAD_SKILL_API_URL），后端直接调官方 gateway，
    用用户的 API Key 认证。调 /user/notebooks 接口获取有笔记的书籍列表。

    Args:
        api_key: 微信读书 API Key。
        limit: 最大拉取条数。``0`` 表示全量同步——持续翻页直到
            ``hasMore != 1`` 为止。安全上限 5000 条（100 页 × 50 条/页）。

    Note: 使用同步 httpx.Client + asyncio.to_thread 而非 httpx.AsyncClient。
    原因：httpx 0.27.2 + httpcore 1.0.9 + OpenSSL 3.5.x 在异步模式下 TLS
    握手会失败（httpcore.ConnectError），同步模式正常。weread 同步是低频
    I/O 操作，同步阻塞在线程池中可接受。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    headers = {
        "Authorization": f"Bearer {stripped_key}",
        "Content-Type": "application/json",
    }

    def _do_fetch() -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        last_sort: int | None = None

        with httpx.Client(timeout=30, follow_redirects=True) as client:
            for _page in range(WEREAD_FETCH_MAX_PAGES):
                batch_size = (
                    WEREAD_FETCH_BATCH_SIZE
                    if limit <= 0 or limit >= WEREAD_FETCH_BATCH_SIZE
                    else limit
                )
                body: dict[str, Any] = {
                    "api_name": "/user/notebooks",
                    "count": batch_size,
                    "skill_version": WEREAD_SKILL_VERSION,
                }
                if last_sort is not None:
                    body["lastSort"] = last_sort

                try:
                    response = client.post(WEREAD_GATEWAY_URL, headers=headers, json=body)
                    response.raise_for_status()
                except httpx.HTTPStatusError as exc:
                    resp_body = redact_weread_sync_error(response.text, api_key).strip()
                    detail = f"微信读书接口返回 {response.status_code}"
                    if resp_body:
                        detail = f"{detail}: {resp_body[:300]}"
                    raise RuntimeError(detail) from exc
                except httpx.HTTPError as exc:
                    raise RuntimeError(f"无法连接微信读书服务: {exc}") from exc

                payload = response.json()
                page_entries = normalize_weread_entries(payload)
                entries.extend(page_entries)

                # limit > 0 时截断到指定条数
                if limit > 0 and len(entries) >= limit:
                    return entries[:limit]

                # 游标分页：hasMore=1 且有 sort 值才继续翻页
                has_more = payload.get("hasMore") if isinstance(payload, dict) else None
                books = payload.get("books") if isinstance(payload, dict) else None
                if has_more != 1 or not books:
                    break
                last_sort = books[-1].get("sort")
                if last_sort is None:
                    break

        return entries

    return await asyncio.to_thread(_do_fetch)


async def ensure_weread_source(db: AsyncSession, *, user_id: int) -> Source:
    """确保用户拥有自己的微信读书 Source（按 owner_user_id 隔离，不共用公共池）。"""
    result = await db.execute(
        select(Source).where(
            Source.url == WEREAD_SOURCE_URL,
            Source.owner_user_id == user_id,
        )
    )
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
        owner_user_id=user_id,
        scope="user",
    )
    db.add(source)
    await db.flush()
    await db.refresh(source)
    return source


async def sync_weread_materials(
    db: AsyncSession,
    integration: UserIntegration,
    *,
    user_id: int,
    api_key: str | None = None,
    limit: int = 0,
) -> dict[str, int | str]:
    if integration.provider != WEREAD_PROVIDER:
        raise ValueError("微信读书 API Key 未配置")
    from app.services.integration_service import integration_api_key

    resolved_api_key = (api_key or integration_api_key(integration) or "").strip()
    if not resolved_api_key:
        raise ValueError("微信读书 API Key 未配置")

    source = await ensure_weread_source(db, user_id=user_id)
    fetched = new = duplicates = 0
    now = datetime.now(UTC)
    try:
        entries = await fetch_weread_materials(resolved_api_key, limit=limit)
        fetched = len(entries)
        for entry in entries:
            content_hash = build_hash(str(entry.get("title") or "") + str(entry.get("url") or ""))
            # 去重按 owner_user_id 隔离：不同用户的同名笔记不算重复
            exists = await db.scalar(
                select(ContentItem.id).where(
                    ContentItem.content_hash == content_hash,
                    ContentItem.owner_user_id == user_id,
                )
            )
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
                    owner_user_id=user_id,
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
            from app._post_sync_pipeline import _request_post_sync_pipeline

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
