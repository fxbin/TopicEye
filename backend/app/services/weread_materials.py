from __future__ import annotations

import asyncio
from datetime import datetime, timezone, UTC
import re
from typing import Any, Dict, Optional, Union
from urllib.parse import quote

import httpx
from sqlalchemy import select, update
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
        # sort 不存在或无效时返回 None，由 sync_weread_materials 决定回退策略。
        sort_value = raw.get("sort")
        if isinstance(sort_value, (int, float)) and sort_value > 1_000_000_000:
            published_at = datetime.fromtimestamp(int(sort_value), tz=UTC)
        else:
            published_at = None
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


# ── WeRead 书籍搜索 & 详情 ──


def _weread_gateway_request(
    api_key: str,
    body: dict[str, Any],
    *,
    timeout: int = 15,
) -> dict[str, Any]:
    """同步调用 WeRead Agent Gateway，返回 JSON dict。"""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.post(WEREAD_GATEWAY_URL, headers=headers, json=body)
        resp.raise_for_status()
        return resp.json()


async def search_weread_books(
    api_key: str,
    keyword: str,
    *,
    count: int = 10,
    scope: int = 10,
    max_idx: int = 0,
) -> dict[str, Any]:
    """通过 WeRead Gateway /store/search 搜索书籍。

    Args:
        api_key: 微信读书 API Key。
        keyword: 搜索关键词。
        count: 每页数量（默认 10）。
        scope: 搜索类型：0=全部, 10=电子书, 14=听书, 6=作者, 12=全文, 13=书单, 2=公众号, 4=文章。
        max_idx: 翻页偏移。

    Returns:
        标准化后的搜索结果 dict，含 books 列表和 hasMore。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    body: dict[str, Any] = {
        "api_name": "/store/search",
        "keyword": keyword,
        "count": count,
        "scope": scope,
        "skill_version": WEREAD_SKILL_VERSION,
    }
    if max_idx > 0:
        body["maxIdx"] = max_idx

    def _do_search() -> dict[str, Any]:
        payload = _weread_gateway_request(stripped_key, body)
        # 展平 results 里各分组的 books
        all_books: list[dict[str, Any]] = []
        results = payload.get("results") or []
        for group in results:
            if not isinstance(group, dict):
                continue
            for item in group.get("books") or []:
                if not isinstance(item, dict):
                    continue
                info = item.get("bookInfo") or {}
                if not info.get("bookId"):
                    continue
                all_books.append(
                    {
                        "bookId": str(info["bookId"]),
                        "title": info.get("title", ""),
                        "author": info.get("author", ""),
                        "translator": info.get("translator", ""),
                        "cover": info.get("cover", ""),
                        "intro": info.get("intro", ""),
                        "deepLink": info.get("deepLink", ""),
                        "category": info.get("category", ""),
                        "publisher": info.get("publisher", ""),
                        "price": info.get("price"),
                        "newRating": info.get("newRating"),
                        "newRatingCount": info.get("newRatingCount"),
                        "newRatingDetail": info.get("newRatingDetail", {}),
                        "readingCount": item.get("readingCount", 0),
                        "scopeLabel": group.get("title", ""),
                    }
                )
        return {
            "books": all_books,
            "hasMore": payload.get("hasMore", 0),
            "sid": payload.get("sid", ""),
            "total": len(all_books),
        }

    return await asyncio.to_thread(_do_search)


async def get_weread_book_info(api_key: str, book_id: str) -> dict[str, Any]:
    """通过 WeRead Gateway /book/info 获取书籍详情。

    Args:
        api_key: 微信读书 API Key。
        book_id: 微信读书书籍 ID。

    Returns:
        标准化后的书籍信息 dict。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    body: dict[str, Any] = {
        "api_name": "/book/info",
        "bookId": str(book_id),
        "skill_version": WEREAD_SKILL_VERSION,
    }

    def _do_fetch_info() -> dict[str, Any]:
        data = _weread_gateway_request(stripped_key, body)
        return {
            "bookId": str(data.get("bookId", "")),
            "title": data.get("title", ""),
            "author": data.get("author", ""),
            "translator": data.get("translator", ""),
            "cover": data.get("cover", ""),
            "intro": data.get("intro", ""),
            "deepLink": data.get("deepLink", ""),
            "category": data.get("category", ""),
            "publisher": data.get("publisher", ""),
            "publishTime": data.get("publishTime", ""),
            "isbn": data.get("isbn", ""),
            "wordCount": data.get("wordCount"),
            "newRating": data.get("newRating"),
            "newRatingCount": data.get("newRatingCount"),
            "newRatingDetail": data.get("newRatingDetail", {}),
        }

    return await asyncio.to_thread(_do_fetch_info)


# ── WeRead 阅读统计 / 热门划线 / 完整书架 ──


async def get_weread_readdata_detail(api_key: str, *, read_type: str = "all") -> dict[str, Any]:
    """通过 WeRead Gateway /readdata/detail 获取阅读统计数据。

    包含阅读时长、天数、读书排行、偏好分析等聚合统计。

    Args:
        api_key: 微信读书 API Key。
        read_type: 统计周期：``all``（总计）、``week``（周）、``month``（月）、``year``（年）。

    Returns:
        标准化后的阅读统计 dict。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    type_map = {"all": 0, "week": 1, "month": 2, "year": 3}
    type_int = type_map.get(read_type, 0)

    body: dict[str, Any] = {
        "api_name": "/readdata/detail",
        "type": type_int,
        "skill_version": WEREAD_SKILL_VERSION,
    }

    def _do_fetch_readdata() -> dict[str, Any]:
        data = _weread_gateway_request(stripped_key, body, timeout=20)
        # 原样透传核心字段，前端按需取用
        return {
            "read_type": read_type,
            "total_read_time": data.get("totalReadTime") or data.get("total_read_time") or 0,
            "total_read_days": data.get("totalReadDays") or data.get("total_read_days") or 0,
            "total_read_book_count": data.get("totalReadBookCount") or data.get("total_read_book_count") or 0,
            "total_note_count": data.get("totalNoteCount") or data.get("total_note_count") or 0,
            "total_mark_count": data.get("totalMarkCount") or data.get("total_mark_count") or 0,
            "ranking_list": data.get("rankingList") or data.get("ranking_list") or [],
            "preference": data.get("preference") or data.get("categoryPreference") or {},
            "raw": data,
        }

    return await asyncio.to_thread(_do_fetch_readdata)


async def get_weread_bestbookmarks(api_key: str, book_id: str, *, count: int = 20) -> dict[str, Any]:
    """通过 WeRead Gateway /book/bestbookmarks 获取书籍热门划线。

    返回按热度排序的热门划线（最多 20 条），可用于阅读决策和跨读者共鸣。

    Args:
        api_key: 微信读书 API Key。
        book_id: 微信读书书籍 ID。
        count: 最大返回条数（默认 20）。

    Returns:
        标准化后的热门划线 dict，含 bookmarks 列表。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    body: dict[str, Any] = {
        "api_name": "/book/bestbookmarks",
        "bookId": str(book_id),
        "count": min(count, 20),
        "skill_version": WEREAD_SKILL_VERSION,
    }

    def _do_fetch_bookmarks() -> dict[str, Any]:
        data = _weread_gateway_request(stripped_key, body)
        # gateway 返回的 items 列表里每项含 chapterName / markText / contentStyle 等
        raw_items = data.get("items") or data.get("bookmarks") or []
        bookmarks: list[dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            mark_text = str(item.get("markText") or item.get("text") or "").strip()
            if not mark_text:
                continue
            bookmarks.append({
                "chapter_name": str(item.get("chapterName") or item.get("chapter") or "").strip(),
                "text": mark_text,
                "content_style": item.get("contentStyle") or item.get("style") or 0,
                "create_time": item.get("createTime") or item.get("create_time") or 0,
            })
        return {
            "book_id": str(book_id),
            "bookmarks": bookmarks[:count],
            "total": len(bookmarks),
        }

    return await asyncio.to_thread(_do_fetch_bookmarks)


async def get_weread_shelf_sync(api_key: str) -> dict[str, Any]:
    """通过 WeRead Gateway /shelf/sync 获取完整书架。

    返回完整书架（包括未开始读的书、听书/讲书），可与笔记本数据对比分析囤书习惯。

    Args:
        api_key: 微信读书 API Key。

    Returns:
        标准化后的书架 dict，含 books 列表和统计摘要。
    """
    stripped_key = (api_key or "").strip()
    if not stripped_key:
        raise ValueError("微信读书 API Key 未配置")

    body: dict[str, Any] = {
        "api_name": "/shelf/sync",
        "skill_version": WEREAD_SKILL_VERSION,
    }

    def _do_fetch_shelf() -> dict[str, Any]:
        data = _weread_gateway_request(stripped_key, body, timeout=20)
        raw_books = data.get("books") or []
        books: list[dict[str, Any]] = []
        for entry in raw_books:
            if not isinstance(entry, dict):
                continue
            book = entry.get("book") if isinstance(entry.get("book"), dict) else entry
            book_id = str(book.get("bookId") or "")
            if not book_id:
                continue
            books.append({
                "book_id": book_id,
                "title": str(book.get("title") or ""),
                "author": str(book.get("author") or ""),
                "cover": str(book.get("cover") or ""),
                "category": str(book.get("category") or ""),
                "deep_link": str(book.get("deepLink") or ""),
                "reading_progress": entry.get("readingProgress") or book.get("readingProgress") or 0,
                "note_count": entry.get("noteCount") or book.get("noteCount") or 0,
                "review_count": entry.get("reviewCount") or book.get("reviewCount") or 0,
                "book_type": entry.get("bookType") or book.get("bookType") or 0,
                "sort": entry.get("sort") or 0,
            })
        # 统计摘要
        total = len(books)
        has_notes = sum(1 for b in books if b["note_count"] > 0 or b["review_count"] > 0)
        no_notes = total - has_notes
        audiobooks = sum(1 for b in books if b["book_type"] == 1)
        return {
            "books": books,
            "total": total,
            "has_notes": has_notes,
            "no_notes": no_notes,
            "audiobook_count": audiobooks,
        }

    return await asyncio.to_thread(_do_fetch_shelf)


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
    fetched = new = duplicates = updated = 0
    now = datetime.now(UTC)
    try:
        entries = await fetch_weread_materials(resolved_api_key, limit=limit)
        fetched = len(entries)
        for entry in entries:
            content_hash = build_hash(str(entry.get("title") or "") + str(entry.get("url") or ""))
            # 去重按 owner_user_id 隔离：不同用户的同名笔记不算重复
            existing_id = await db.scalar(
                select(ContentItem.id).where(
                    ContentItem.content_hash == content_hash,
                    ContentItem.owner_user_id == user_id,
                )
            )
            if existing_id:
                duplicates += 1
                # 已存在的条目：用最新的 sort 时间戳和摘要更新，
                # 保证排序与微信读书平台一致
                entry_published_at = entry.get("published_at")
                entry_summary = entry.get("summary")
                update_values: dict[str, Any] = {}
                if entry_published_at is not None:
                    update_values["published_at"] = entry_published_at
                if entry_summary is not None:
                    update_values["summary"] = entry_summary
                if update_values:
                    await db.execute(
                        update(ContentItem)
                        .where(ContentItem.id == existing_id)
                        .values(**update_values)
                    )
                    updated += 1
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
        if new or updated:
            invalidate_content_read_caches()
        if new:
            from app._post_sync_pipeline import _request_post_sync_pipeline

            _request_post_sync_pipeline({"new": new})
        return {
            "fetched": fetched,
            "new": new,
            "duplicates": duplicates,
            "updated": updated,
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
