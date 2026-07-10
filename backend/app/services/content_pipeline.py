"""
Content ingestion pipeline.

Orchestrates fetching, deduplication, classification, and storage for a
single source. Uses the scraper registry to dispatch by SourceType.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from datetime import datetime, timezone, UTC
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import database_profile
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceType, SourceStatus
from app.services.classifier import classify, extract_tags, classify_async
from app.services.llm_pre_filter import apply_pre_filter
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.dedup import build_hash
from app.services.scraper_http import build_scraper_client_kwargs
from app.services.scrapers import get_scraper_cls
# Error redaction extracted to _error_redaction.py (pure functions + constants)
from app.services._error_redaction import redact_source_sync_error  # noqa: F401 — re-export

logger = logging.getLogger(__name__)



async def ingest_from_source(source: Source, db: AsyncSession) -> dict[str, int]:
    """
    Full ingestion pipeline for a single source.

    Steps:
        1. Look up the scraper class for this source_type.
        2. Fetch content entries.
        3. Compute content_hash for each entry and skip duplicates.
        4. Classify and tag each new entry.
        5. Persist ContentItem records.
        6. Update source.last_sync_at and status.

    Returns ``{"fetched": N, "new": N, "duplicates": N}``.
    """
    try:
        return await asyncio.wait_for(
            _ingest_from_source_inner(source, db),
            timeout=settings.SOURCE_SYNC_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        message = f"Source sync timed out after {settings.SOURCE_SYNC_TIMEOUT_SECONDS}s"
        logger.warning("Source %s (%d): %s", source.name, source.id, message)
        _update_source_error(source, message)
        await db.flush()
        return {"fetched": 0, "new": 0, "duplicates": 0}


async def _ingest_from_source_inner(source: Source, db: AsyncSession) -> dict[str, int]:
    fetched_count = 0
    new_count = 0
    duplicate_count = 0
    started_at = time.perf_counter()

    try:
        # ── Step 1: Resolve scraper ──────────────────────────────────
        source_type = source.source_type
        source_type_str = source_type.value if source_type else "RSS"

        # Skip ZHIHU: its hot topics are now served exclusively via trending radar
        # and should not be duplicated into the content feed.
        if source_type == SourceType.ZHIHU or source_type_str.upper() == "ZHIHU":
            logger.info("Source '%s' (ZHIHU): skipped — topics served via trending radar", source.name)
            _update_source_status(source, SourceStatus.ACTIVE)
            await db.flush()
            return {"fetched": 0, "new": 0, "duplicates": 0}

        scraper_cls = get_scraper_cls(source_type_str)

        if scraper_cls is None:
            logger.warning(
                "No scraper registered for source_type '%s' (source %d)",
                source_type_str,
                source.id,
            )
            _update_source_error(source, f"No scraper registered for source_type '{source_type_str}'")
            await db.flush()
            return {"fetched": 0, "new": 0, "duplicates": 0}

        # Build scraper config from source metadata (stored as JSON in DB)
        source_config = {}
        if source.keyword:
            import json

            try:
                source_config = json.loads(source.keyword)
            except (json.JSONDecodeError, TypeError):
                # keyword is a plain string, use as search_query for twitter
                if source_type_str == "X":
                    source_config = {"search_query": source.keyword}

        scraper = scraper_cls(source_url=source.url, source_config=source_config)

        # ── Step 2: Fetch ────────────────────────────────────────────
        client_kwargs = build_scraper_client_kwargs(
            source.url,
            etag=source.etag,
            last_modified=source.last_modified,
        )

        fetch_started_at = time.perf_counter()
        async with httpx.AsyncClient(**client_kwargs) as client:
            entries = await scraper.fetch(client)
        fetched_count = len(entries)

        # Persist the latest ETag / Last-Modified so the next fetch can use
        # them. Only RSS scraper currently populates these (others leave the
        # attributes absent); getattr keeps the read side scraper-agnostic.
        new_etag = getattr(scraper, "_latest_etag", None)
        new_last_modified = getattr(scraper, "_latest_last_modified", None)
        if new_etag is not None or new_last_modified is not None:
            if new_etag is not None:
                source.etag = new_etag
            if new_last_modified is not None:
                source.last_modified = new_last_modified
        fetch_elapsed_ms = int((time.perf_counter() - fetch_started_at) * 1000)

        if not entries:
            logger.info(
                "Source %s (%d): no entries fetched in %dms",
                source.name,
                source.id,
                fetch_elapsed_ms,
            )
            _update_source_status(source, SourceStatus.ACTIVE)
            await db.flush()
            return {"fetched": 0, "new": 0, "duplicates": 0}

        # ── Step 3: Dedup via content_hash ───────────────────────────
        # 先规范化超长字段：截断到列上限，避免 PostgreSQL varchar 溢出整批回滚。
        # arXiv 论文 author 经常几十人（700+ 字符），远超 author varchar(255)。
        _FIELD_MAX = {"title": 480, "author": 250}
        for entry in entries:
            for field, max_len in _FIELD_MAX.items():
                val = entry.get(field, "")
                if isinstance(val, str) and len(val) > max_len:
                    entry[field] = val[: max_len - 1] + "…"

        for entry in entries:
            text_for_hash = entry.get("title", "") + entry.get("url", "")
            entry["_content_hash"] = build_hash(text_for_hash)

        incoming_hashes = {e["_content_hash"] for e in entries}

        # 去重范围:同 platform 下按 content_hash 全局去重。
        # arXiv 等聚合平台的论文会同时出现在多个分类源(cs.AI/cs.CL/cs.LG),
        # 之前按 source_id 隔离去重导致同一 URL 被每个源各入一次。
        # 改为按 platform 分组,同一平台下相同内容只入库一次,归属首个抓到的源。
        result = await db.execute(
            select(ContentItem.content_hash)
            .join(Source, Source.id == ContentItem.source_id)
            .where(
                ContentItem.content_hash.in_(incoming_hashes),
                Source.platform == source.platform,
            )
        )
        existing_hashes = {row[0] for row in result.all()}

        # ── Step 4+5: Classify, tag and persist ──────────────────────
        category_names = await _get_active_category_names(db)
        candidate_entries: list[dict[str, Any]] = []
        for entry in entries:
            ch = entry["_content_hash"]
            if ch in existing_hashes:
                duplicate_count += 1
                continue
            candidate_entries.append(entry)
            existing_hashes.add(ch)

        classify_started_at = time.perf_counter()
        classified_entries = await _classify_entries_concurrently(
            candidate_entries,
            category_names=category_names,
        )
        classify_elapsed_ms = int((time.perf_counter() - classify_started_at) * 1000)

        await _register_new_categories(db, [class_result for _, class_result in classified_entries])

        new_items: list[ContentItem] = []
        metrics_records: list[dict | None] = []
        category_counts: dict[str, int] = {}
        for entry, class_result in classified_entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "")

            category = class_result["category"]
            tags = class_result["tags"]
            entry_hash = entry.get("_content_hash")  # per-entry hash (fix: was reusing outer-loop ch)

            item = ContentItem(
                title=title,
                url=entry.get("url", ""),
                source_id=source.id,
                source_name=source.name,
                source_type=source_type_str,
                platform=source.platform,
                owner_user_id=source.owner_user_id,
                author=entry.get("author"),
                published_at=entry.get("published_at"),
                content_hash=entry_hash,
                summary=summary or None,
                raw_content=entry.get("raw_content") or None,
                cover_url=entry.get("cover_url"),
                category=category,
                tags=tags if tags else None,
                status=ContentStatus.PENDING,
            )
            new_items.append(item)
            metrics_records.append(_build_metrics_record(entry))
            # LLM 规则过滤层（参照 content-signal-radar lowSignalPenalty）：
            # 命中硬低信号/自吹/过短 → 标 skip_analysis=True（不入 LLM 队列）
            apply_pre_filter(item)
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1
            new_count += 1

        # ── Persist via dialect INSERT + ON CONFLICT DO NOTHING ──
        # DB-layer dedup is the concurrency-safe backstop; SELECT IN above
        # only optimises the happy path. RETURNING gives us the inserted
        # ids so we can attach ContentMetrics without orphaning them.
        db_elapsed_ms = 0
        if new_items:
            # dialect.insert does not trigger ORM `default=` callables, so
            # populate NOT-NULL columns that have no server_default.
            now = datetime.now(UTC)
            for item in new_items:
                if item.crawled_at is None:
                    item.crawled_at = now
                if item.created_at is None:
                    item.created_at = now
                if item.updated_at is None:
                    item.updated_at = now
                if item.is_favorited is None:
                    item.is_favorited = False
                if item.similarity_score is None:
                    item.similarity_score = 0.0

            # Exclude autoincrement PK from explicit values: PG rejects
            # NULL on a SERIAL PK (NotNullViolationError) while SQLite silently
            # generates a rowid. Excluding makes both backends auto-generate.
            column_names = [c.name for c in ContentItem.__table__.columns if not (c.primary_key and c.autoincrement)]
            new_records = [{col: getattr(item, col) for col in column_names} for item in new_items]
            insert_stmt = _backend_insert(ContentItem).values(new_records)
            insert_stmt = insert_stmt.on_conflict_do_nothing(
                index_elements=["source_id", "content_hash"],
            ).returning(ContentItem.id)
            db_started_at = time.perf_counter()
            result = await db.execute(insert_stmt)
            inserted_ids = [row[0] for row in result.all()]

            # Attach ContentMetrics to successfully inserted rows only.
            from app.models.metrics import ContentMetrics

            skipped_by_conflict = len(new_items) - len(inserted_ids)
            if skipped_by_conflict:
                duplicate_count += skipped_by_conflict
                new_count -= skipped_by_conflict
            for content_id, metrics_rec in zip(inserted_ids, metrics_records):
                if metrics_rec is None:
                    continue
                metrics_rec["content_id"] = content_id
                db.add(ContentMetrics(**metrics_rec))

            await _increment_category_counts(db, category_counts)
            invalidate_content_read_caches()
            db_elapsed_ms = int((time.perf_counter() - db_started_at) * 1000)

        # ── Step 6: Update source ────────────────────────────────────
        _update_source_status(source, SourceStatus.ACTIVE)
        await db.flush()

        logger.info(
            "Source %s (%d): fetched=%d, new=%d, dupes=%d, fetch=%dms, classify=%dms, db=%dms, total=%dms",
            source.name,
            source.id,
            fetched_count,
            new_count,
            duplicate_count,
            fetch_elapsed_ms,
            classify_elapsed_ms,
            db_elapsed_ms,
            int((time.perf_counter() - started_at) * 1000),
        )

    except Exception as exc:
        error_message = str(exc) or exc.__class__.__name__
        safe_message = redact_source_sync_error(error_message)
        logger.error(
            "Error ingesting source %s (%d): %s",
            source.name,
            source.id,
            safe_message,
        )
        _update_source_error(source, safe_message)
        await db.flush()

    return {"fetched": fetched_count, "new": new_count, "duplicates": duplicate_count}


async def _classify_entries_concurrently(
    entries: list[dict[str, Any]],
    *,
    category_names: list[str],
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Classify fetched entries with bounded concurrency while preserving order."""
    if not entries:
        return []

    concurrency = _normalize_classification_concurrency()
    semaphore = asyncio.Semaphore(concurrency)

    async def classify_one(entry: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
        async with semaphore:
            class_result = await classify_entry_readonly(
                entry.get("title", ""),
                entry.get("summary", ""),
                category_names=category_names,
            )
            return entry, class_result

    return await asyncio.gather(*(classify_one(entry) for entry in entries))


def _normalize_classification_concurrency() -> int:
    try:
        parsed = int(settings.CLASSIFICATION_WORKER_CONCURRENCY)
    except (TypeError, ValueError):
        parsed = 1
    return max(1, min(parsed, 10))


async def classify_entry_readonly(
    title: str,
    summary: str,
    *,
    category_names: list[str],
) -> dict[str, Any]:
    """Classify one entry without using the ingestion DB session concurrently."""
    return await classify_async(
        title,
        summary,
        None,
        category_names=category_names,
        auto_create_new_category=False,
    )


async def _register_new_categories(
    db: AsyncSession,
    classification_results: list[dict[str, Any]],
) -> None:
    """Create newly discovered categories serially in the ingestion transaction."""
    new_categories: list[str] = []
    for result in classification_results:
        category = str(result.get("category") or "").strip()
        if not category or not result.get("is_new_category") or category in new_categories:
            continue
        new_categories.append(category)

    if not new_categories:
        return

    from app.repositories.category_repo import CategoryRepository

    category_repo = CategoryRepository(db)
    for category in new_categories:
        await category_repo.get_or_create(
            name=category,
            description="LLM自动发现的分类",
            is_auto_created=True,
        )


def _update_source_status(source: Source, status: SourceStatus) -> None:
    """Set source sync metadata."""
    source.last_sync_at = datetime.now(UTC)
    source.status = status
    source.sync_error = None
    source.updated_at = datetime.now(UTC)


def _update_source_error(source: Source, message: str) -> None:
    """Record a failed sync attempt without causing immediate retry loops."""
    source.last_sync_at = datetime.now(UTC)
    source.status = SourceStatus.ERROR
    source.sync_error = redact_source_sync_error(message)[:500]
    source.updated_at = datetime.now(UTC)


async def _get_active_category_names(db: AsyncSession) -> list[str]:
    from app.repositories.category_repo import CategoryRepository

    names = await CategoryRepository(db).get_active_names()
    return names or classify_default_categories()


def classify_default_categories() -> list[str]:
    from app.services.classifier import CATEGORIES

    return CATEGORIES.copy()


async def _increment_category_counts(db: AsyncSession, counts: dict[str, int]) -> None:
    """
    Batch-increment category content_count in the current transaction.

    Do not spawn background tasks with the request/session object; SQLAlchemy
    sessions are not safe for concurrent use and SQLite has a single writer.
    One UPDATE per unique category = minimal DB round-trips.
    """
    if not counts:
        return

    for cat_name, count in counts.items():
        await db.execute(
            text("UPDATE categories SET content_count = content_count + :n WHERE name = :name"),
            {"n": count, "name": cat_name},
        )


def _build_metrics_record(entry: dict) -> dict | None:
    """Extract platform-specific metrics (e.g. _reddit_meta, _zhihu_meta) into a
    plain dict ready to be persisted once the parent ContentItem has an id.

    Returns None when the entry has no recognised metrics meta.
    """
    # ── Reddit metrics ──
    reddit_meta = entry.get("_reddit_meta")
    if reddit_meta:
        score = reddit_meta.get("score", 0)
        num_comments = reddit_meta.get("num_comments", 0)
        subscribers = reddit_meta.get("subreddit_subscribers", 0)

        engagement_rate = 0.0
        if subscribers > 0:
            engagement_rate = round((score + num_comments) / subscribers * 100, 4)

        explosion_ratio = 0.0
        if subscribers > 0:
            explosion_ratio = round(score / subscribers * 1000, 4)

        return dict(
            likes=score,
            comments=num_comments,
            shares=0,
            favorites=0,
            followers_count=subscribers,
            engagement_rate=engagement_rate,
            explosion_ratio=explosion_ratio,
        )

    # ── Zhihu metrics ──
    zhihu_meta = entry.get("_zhihu_meta")
    if zhihu_meta:
        hot_score_raw = zhihu_meta.get("hot_score", 0)
        rank_raw = zhihu_meta.get("rank", 0)
        try:
            hot_score = int(float(str(hot_score_raw).replace("_", "")))
        except (ValueError, TypeError):
            hot_score = 0
        try:
            rank = int(float(str(rank_raw).replace("_", "")))
        except (ValueError, TypeError):
            rank = 0

        # For Zhihu hot list, hot_score is the primary engagement metric
        # Use a simple explosion_ratio based on rank (lower rank = higher)
        explosion_ratio = 0.0
        if rank > 0:
            explosion_ratio = round(1000.0 / rank, 4)

        return dict(
            likes=hot_score,
            comments=0,
            shares=0,
            favorites=0,
            followers_count=0,
            engagement_rate=round(float(hot_score) / 10000, 4) if hot_score > 0 else 0.0,
            explosion_ratio=explosion_ratio,
        )

    # ── Douyin Hot metrics ──
    douyin_meta = entry.get("_douyin_hot_meta")
    if douyin_meta:
        hot_score = douyin_meta.get("hot_score", 0)
        rank = douyin_meta.get("rank", 0)

        explosion_ratio = 0.0
        if rank > 0:
            explosion_ratio = round(1000.0 / rank, 4)

        return dict(
            likes=hot_score,
            comments=0,
            shares=0,
            favorites=0,
            followers_count=0,
            engagement_rate=round(float(hot_score) / 10000, 4) if hot_score > 0 else 0.0,
            explosion_ratio=explosion_ratio,
        )

    # ── Twitter RSS metrics ──
    if entry.get("_twitter_rss_meta"):
        # Basic metrics from xgo.ing RSS — limited data available
        return dict(
            likes=0,
            comments=0,
            shares=0,
            favorites=0,
            followers_count=0,
            engagement_rate=0.0,
            explosion_ratio=0.0,
        )

    return None


def _backend_insert(model):
    """Pick the dialect-appropriate INSERT for ``on_conflict_*`` upserts."""
    if database_profile.is_sqlite:
        return sqlite_insert(model)
    if database_profile.is_postgresql:
        return postgresql_insert(model)
    raise RuntimeError(f"Unsupported database backend for on_conflict upsert: {database_profile.backend}")
