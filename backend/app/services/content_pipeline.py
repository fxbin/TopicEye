"""
Content ingestion pipeline.

Orchestrates fetching, deduplication, classification, and storage for a
single source. Uses the scraper registry to dispatch by SourceType.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import database_profile
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType

# Error redaction extracted to _error_redaction.py (pure functions + constants)
from app.services._error_redaction import redact_source_sync_error  # noqa: F401 — re-export
from app.services.classifier import classify_async
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.content_summary import clean_content_summary
from app.services.dedup import build_hash
from app.services.llm_pre_filter import apply_pre_filter
from app.services.scraper_http import build_scraper_client_kwargs
from app.services.scrapers import get_scraper_cls

logger = logging.getLogger(__name__)


def _ensure_datetime(value: Any) -> datetime | None:
    """Defensive normalisation: convert str/ISO-timestamp to datetime.

    Scrapers should already return datetime objects, but asyncpg rejects
    ISO strings for TIMESTAMP columns. This guard catches any future
    scraper that accidentally returns a string.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            from dateutil.parser import isoparse
            return isoparse(value)
        except Exception:
            logger.warning("Could not parse published_at string: %r", value)
            return None
    return None



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
        # asyncio.wait_for cancels the inner task, which may leave the DB
        # session in a dirty state (an interrupted query mid-flight).  A
        # bare db.flush() on a dirty session raises InvalidRequestError, so
        # the ERROR status update is silently lost — the source stays in
        # SYNCING until the rescan job auto-resets it minutes later.
        #
        # Fix: rollback the dirty session first, then re-fetch the source
        # (the ORM object may be detached after rollback) and update its
        # status in a clean transaction.
        # ``rollback`` expires ORM attributes, so capture the primary key
        # before rolling back rather than triggering an implicit async load
        # through ``source.id`` afterwards.
        source_id = source.id
        await db.rollback()
        fresh = await db.get(Source, source_id)
        if fresh is not None:
            _update_source_error(fresh, message)
            await db.commit()
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

        # ── Step 4+5: Pre-filter, classify eligible entries, persist ─
        candidate_entries: list[dict[str, Any]] = []
        for entry in entries:
            ch = entry["_content_hash"]
            if ch in existing_hashes:
                duplicate_count += 1
                continue
            candidate_entries.append(entry)
            existing_hashes.add(ch)

        new_items: list[ContentItem] = []
        metrics_records: list[dict | None] = []
        eligible_entries: list[dict[str, Any]] = []
        for entry in candidate_entries:
            title = entry.get("title", "")
            # RSS/Atom descriptions are often HTML.  Normalise at the model
            # boundary so every scraper stores a display-safe, readable
            # summary instead of relying on individual scraper conventions.
            summary = clean_content_summary(entry.get("summary", ""))
            entry["summary"] = summary
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
                published_at=_ensure_datetime(entry.get("published_at")),
                content_hash=entry_hash,
                summary=summary or None,
                raw_content=entry.get("raw_content") or None,
                cover_url=entry.get("cover_url"),
                status=ContentStatus.PENDING,
            )
            # LLM 规则过滤层（参照 content-signal-radar lowSignalPenalty）：
            # 在分类前执行，避免低信号内容占用模型池和分类并发槽位。
            is_skipped = apply_pre_filter(item)
            new_items.append(item)
            metrics_records.append(_build_metrics_record(entry))
            if not is_skipped:
                eligible_entries.append(entry)

        # Persist the crawl result before any remote LLM work.  Classification
        # may be slow, rate-limited, or unavailable; it must not be able to
        # turn a successfully fetched item into a lost item.  A later analysis
        # worker can still process the PENDING row if this invocation stops
        # before classification finishes.
        inserted_content_ids: dict[str, int] = {}
        db_elapsed_ms = 0
        if new_items:
            db_started_at = time.perf_counter()
            inserted_content_ids = await _persist_new_content_items(
                db, new_items, metrics_records, category_counts={}
            )
            await db.commit()
            invalidate_content_read_caches()
            db_elapsed_ms = int((time.perf_counter() - db_started_at) * 1000)

        skipped_by_conflict = len(new_items) - len(inserted_content_ids)
        if skipped_by_conflict:
            duplicate_count += skipped_by_conflict
        new_count = len(inserted_content_ids)

        # A concurrent sync can win the unique constraint race.  Only run the
        # expensive classifier for rows this invocation actually inserted.
        eligible_entries = [
            entry for entry in eligible_entries if entry["_content_hash"] in inserted_content_ids
        ]

        classify_started_at = time.perf_counter()
        classified_entries: list[tuple[dict[str, Any], dict[str, Any]]] = []
        category_counts: dict[str, int] = {}
        if eligible_entries:
            category_names = await _get_active_category_names(db)
            classified_entries = await _classify_entries_concurrently(
                eligible_entries,
                category_names=category_names,
            )
            await _register_new_categories(db, [class_result for _, class_result in classified_entries])

        for entry, class_result in classified_entries:
            category = class_result["category"]
            tags = class_result["tags"]
            await db.execute(
                update(ContentItem)
                .where(ContentItem.id == inserted_content_ids[entry["_content_hash"]])
                .values(category=category, tags=tags if tags else None)
            )
            if category:
                category_counts[category] = category_counts.get(category, 0) + 1

        classify_elapsed_ms = int((time.perf_counter() - classify_started_at) * 1000)
        await _increment_category_counts(db, category_counts)

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


async def _persist_new_content_items(
    db: AsyncSession,
    new_items: list[ContentItem],
    metrics_records: list[dict | None],
    category_counts: dict[str, int],
) -> dict[str, int]:
    """通过方言 INSERT + ON CONFLICT DO NOTHING 持久化新内容项。

    DB 层去重是并发安全的兜底；上方的 SELECT IN 只优化快乐路径。
    RETURNING 返回实际插入的 id，用于挂载 ContentMetrics 避免孤儿记录。

    Returns:
        本次实际写入的 ``content_hash -> content_id`` 映射。  ``content_hash``
        不在映射中即表示被并发写入方的唯一约束冲突跳过。
    """
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
        if item.analysis_attempts is None:
            item.analysis_attempts = 0
    # Exclude autoincrement PK from explicit values: PG rejects
    # NULL on a SERIAL PK (NotNullViolationError) while SQLite silently
    # generates a rowid. Excluding makes both backends auto-generate.
    column_names = [c.name for c in ContentItem.__table__.columns if not (c.primary_key and c.autoincrement)]
    new_records = [{col: getattr(item, col) for col in column_names} for item in new_items]
    insert_stmt = _backend_insert(ContentItem).values(new_records)
    insert_stmt = insert_stmt.on_conflict_do_nothing(
        index_elements=["source_id", "content_hash"],
    ).returning(ContentItem.id, ContentItem.content_hash)
    result = await db.execute(insert_stmt)
    inserted_content_ids = {row.content_hash: row.id for row in result.all()}

    # Attach ContentMetrics to successfully inserted rows only.
    from app.models.metrics import ContentMetrics

    for item, metrics_rec in zip(new_items, metrics_records, strict=True):
        if metrics_rec is None:
            continue
        content_id = inserted_content_ids.get(item.content_hash)
        if content_id is None:
            continue
        metrics_rec["content_id"] = content_id
        db.add(ContentMetrics(**metrics_rec))

    await _increment_category_counts(db, category_counts)
    return inserted_content_ids


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
    if entry.get("_reddit_meta"):
        return _build_reddit_metrics(entry["_reddit_meta"])
    if entry.get("_zhihu_meta"):
        return _build_zhihu_metrics(entry["_zhihu_meta"])
    if entry.get("_douyin_hot_meta"):
        return _build_douyin_metrics(entry["_douyin_hot_meta"])
    if entry.get("_twitter_rss_meta"):
        # xgo.ing RSS 数据有限，暂只占位
        return {
            "likes": 0,
            "comments": 0,
            "shares": 0,
            "favorites": 0,
            "followers_count": 0,
            "engagement_rate": 0.0,
            "explosion_ratio": 0.0,
        }
    return None


def _build_reddit_metrics(meta: dict) -> dict:
    """Reddit 子版块指标：score / num_comments / subreddit_subscribers。"""
    score = meta.get("score", 0)
    num_comments = meta.get("num_comments", 0)
    subscribers = meta.get("subreddit_subscribers", 0)

    engagement_rate = 0.0
    if subscribers > 0:
        engagement_rate = round((score + num_comments) / subscribers * 100, 4)

    explosion_ratio = 0.0
    if subscribers > 0:
        explosion_ratio = round(score / subscribers * 1000, 4)

    return {
        "likes": score,
        "comments": num_comments,
        "shares": 0,
        "favorites": 0,
        "followers_count": subscribers,
        "engagement_rate": engagement_rate,
        "explosion_ratio": explosion_ratio,
    }


def _build_zhihu_metrics(meta: dict) -> dict:
    """知乎热榜指标：hot_score / rank（rank 越小越靠前）。"""
    hot_score_raw = meta.get("hot_score", 0)
    rank_raw = meta.get("rank", 0)
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

    return {
        "likes": hot_score,
        "comments": 0,
        "shares": 0,
        "favorites": 0,
        "followers_count": 0,
        "engagement_rate": round(float(hot_score) / 10000, 4) if hot_score > 0 else 0.0,
        "explosion_ratio": explosion_ratio,
    }


def _build_douyin_metrics(meta: dict) -> dict:
    """抖音热榜指标：hot_score / rank。"""
    hot_score = meta.get("hot_score", 0)
    rank = meta.get("rank", 0)

    explosion_ratio = 0.0
    if rank > 0:
        explosion_ratio = round(1000.0 / rank, 4)

    return {
        "likes": hot_score,
        "comments": 0,
        "shares": 0,
        "favorites": 0,
        "followers_count": 0,
        "engagement_rate": round(float(hot_score) / 10000, 4) if hot_score > 0 else 0.0,
        "explosion_ratio": explosion_ratio,
    }


def _backend_insert(model):
    """Pick the dialect-appropriate INSERT for ``on_conflict_*`` upserts."""
    if database_profile.is_sqlite:
        return sqlite_insert(model)
    if database_profile.is_postgresql:
        return postgresql_insert(model)
    raise RuntimeError(f"Unsupported database backend for on_conflict upsert: {database_profile.backend}")
