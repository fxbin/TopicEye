from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.category import Category
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType
from app.repositories.source_repo import SourceRepository
from app.services import content_pipeline
from app.services.content_pipeline import _update_source_error
from app.services.scraper_http import build_scraper_client_kwargs


def test_update_source_error_uses_readable_fallback_for_blank_message():
    source = Source(
        name="Broken API",
        url="https://example.com/api/news",
        source_type=SourceType.API,
    )

    _update_source_error(source, "")

    assert source.status == SourceStatus.ERROR
    assert source.sync_error == "信源同步失败"
    assert source.last_sync_at is not None


def test_build_scraper_client_kwargs_skips_explicit_proxy_for_loopback(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")

    local_kwargs = build_scraper_client_kwargs("http://127.0.0.1:8999/api/news")
    remote_kwargs = build_scraper_client_kwargs("https://example.com/api/news")

    assert local_kwargs["trust_env"] is False
    assert "proxy" not in local_kwargs
    assert remote_kwargs["trust_env"] is False
    assert remote_kwargs["proxy"] == "http://127.0.0.1:7890"
    # New helper also injects a UA / Accept headers so scrapers can use 304
    # out of the box and avoid some public services' UA blocks.
    assert local_kwargs["headers"]["User-Agent"].startswith("TopicEye/")
    assert "application/rss+xml" in local_kwargs["headers"]["Accept"]


@pytest.mark.asyncio
async def test_ingest_timeout_rolls_back_then_persists_source_error(monkeypatch):
    """Cancellation must not leave the source stuck in SYNCING."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async def interrupted_sync(source, db):
        db.add(
            ContentItem(
                title="will be rolled back",
                url="https://example.com/interrupted",
                source_id=source.id,
            )
        )
        raise TimeoutError

    monkeypatch.setattr(content_pipeline, "_ingest_from_source_inner", interrupted_sync)
    monkeypatch.setattr(content_pipeline.settings, "SOURCE_SYNC_TIMEOUT_SECONDS", 1)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Timeout Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                status=SourceStatus.SYNCING,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            assert await content_pipeline.ingest_from_source(source, db) == {
                "fetched": 0,
                "new": 0,
                "duplicates": 0,
            }

        async with session_factory() as verify_db:
            stored_source = await verify_db.get(Source, 1)
            interrupted_rows = (await verify_db.execute(select(ContentItem))).scalars().all()

        assert stored_source is not None
        assert stored_source.status == SourceStatus.ERROR
        assert stored_source.sync_error == "Source sync timed out after 1s"
        assert interrupted_rows == []
    finally:
        await engine.dispose()


def test_build_scraper_client_kwargs_emits_conditional_request_headers():
    kwargs = build_scraper_client_kwargs(
        "https://example.com/feed",
        etag='"abc123"',
        last_modified="Wed, 21 Oct 2026 07:28:00 GMT",
    )
    headers = kwargs["headers"]
    assert headers["If-None-Match"] == '"abc123"'
    assert headers["If-Modified-Since"] == "Wed, 21 Oct 2026 07:28:00 GMT"


@pytest.mark.asyncio
async def test_claim_source_sync_uses_last_sync_lease():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Lease Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            first = await SourceRepository(db).claim_sync(1, lease_seconds=60)
            await db.commit()
            second = await SourceRepository(db).claim_sync(1, lease_seconds=60)

            assert first is not None
            assert first.status == SourceStatus.SYNCING
            assert second is None

        async with session_factory() as db:
            source = await db.get(Source, 1)
            source.last_sync_at = source.last_sync_at - timedelta(seconds=120)
            await db.commit()

            stale = await SourceRepository(db).claim_sync(1, lease_seconds=60)

            assert stale is not None
            assert stale.status == SourceStatus.SYNCING

        async with session_factory() as db:
            source = await db.get(Source, 1)
            source.status = SourceStatus.ACTIVE
            await db.commit()

            completed = await SourceRepository(db).claim_sync(1, lease_seconds=60)

            assert completed is not None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_from_source_reuses_category_names_per_source(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {
                    "title": "first",
                    "url": "https://example.com/first",
                    "summary": "A detailed technical article about AI systems and evaluation.",
                },
                {
                    "title": "second",
                    "url": "https://example.com/second",
                    "summary": "A detailed technical article about AI systems and evaluation.",
                },
            ]

    category_loads = 0
    classified_with = []
    auto_create_flags = []

    async def fake_get_active_category_names(db):
        nonlocal category_loads
        category_loads += 1
        return ["AI", "产品"]

    async def fake_classify_async(title, summary, db, category_names=None, auto_create_new_category=True):
        classified_with.append(category_names)
        auto_create_flags.append(auto_create_new_category)
        return {"category": "AI", "tags": ["ai"], "is_new_category": False, "confidence": 0.8}

    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", fake_get_active_category_names)
    monkeypatch.setattr(content_pipeline, "classify_async", fake_classify_async)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            await db.commit()

            rows = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()

        assert stats == {"fetched": 2, "new": 2, "duplicates": 0}
        assert category_loads == 1
        assert classified_with == [["AI", "产品"], ["AI", "产品"]]
        assert auto_create_flags == [False, False]
        assert [row.category for row in rows] == ["AI", "AI"]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_from_source_normalizes_html_summary_before_persisting_or_classifying(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {
                    "title": "Show HN: Label Your AI Writing as AI Writing",
                    "url": "https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting",
                    "summary": (
                        '<p>Article URL: <a href="https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting">'
                        "https://www.raymondyxu.com/blog/labelYourAIWritingAsAIWriting</a></p>"
                        '<p>Comments URL: <a href="https://news.ycombinator.com/item?id=1">'
                        "https://news.ycombinator.com/item?id=1</a></p>"
                    ),
                }
            ]

    classified_summaries = []

    async def fake_get_active_category_names(db):
        return ["AI"]

    async def fake_classify_async(title, summary, db, category_names=None, auto_create_new_category=True):
        classified_summaries.append(summary)
        return {"category": "AI", "tags": ["disclosure"], "is_new_category": False, "confidence": 0.8}

    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", fake_get_active_category_names)
    monkeypatch.setattr(content_pipeline, "classify_async", fake_classify_async)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Hacker News",
                url="https://news.ycombinator.com/rss",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            stored = await db.scalar(select(ContentItem))

        assert stats == {"fetched": 1, "new": 1, "duplicates": 0}
        assert stored is not None
        assert stored.summary is None
        assert classified_summaries == [""]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_from_source_classifies_new_entries_with_bounded_concurrency(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {
                    "title": f"item {index}",
                    "url": f"https://example.com/item-{index}",
                    "summary": "A detailed technical article about AI systems and evaluation.",
                }
                for index in range(4)
            ]

    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_get_active_category_names(db):
        return ["AI", "产品"]

    async def fake_classify_async(title, summary, db, category_names=None, auto_create_new_category=True):
        nonlocal active, max_active
        assert auto_create_new_category is False
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.03)
        async with lock:
            active -= 1
        return {"category": "AI", "tags": [title], "is_new_category": False, "confidence": 0.8}

    monkeypatch.setattr(content_pipeline.settings, "CLASSIFICATION_WORKER_CONCURRENCY", 2)
    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", fake_get_active_category_names)
    monkeypatch.setattr(content_pipeline, "classify_async", fake_classify_async)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Concurrent Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            await db.commit()

            rows = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()

        assert stats == {"fetched": 4, "new": 4, "duplicates": 0}
        assert max_active == 2
        assert [row.title for row in rows] == ["item 0", "item 1", "item 2", "item 3"]
        assert [row.tags for row in rows] == [["item 0"], ["item 1"], ["item 2"], ["item 3"]]
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_from_source_pre_filters_before_llm_classification(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {"title": "GM everyone!", "url": "https://example.com/noise", "summary": ""},
                {
                    "title": "New LLM benchmark improves agent reliability",
                    "url": "https://example.com/signal",
                    "summary": "A detailed technical evaluation with reproducible results.",
                },
            ]

    classified_titles = []

    async def fake_get_active_category_names(db):
        return ["AI"]

    async def fake_classify_entry_readonly(title, summary, *, category_names):
        classified_titles.append(title)
        return {"category": "AI", "tags": ["benchmark"], "is_new_category": False, "confidence": 0.8}

    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", fake_get_active_category_names)
    monkeypatch.setattr(content_pipeline, "classify_entry_readonly", fake_classify_entry_readonly)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Pre-filter Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            await db.commit()
            rows = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()

        assert stats == {"fetched": 2, "new": 2, "duplicates": 0}
        assert classified_titles == ["New LLM benchmark improves agent reliability"]
        assert rows[0].skip_analysis is True
        assert rows[0].category is None
        assert rows[1].skip_analysis is False
        assert rows[1].category == "AI"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_from_source_registers_new_categories_after_parallel_classification(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {
                    "title": "new category item",
                    "url": "https://example.com/new-category",
                    "summary": "A detailed technical article about AI systems and evaluation.",
                },
            ]

    async def fake_get_active_category_names(db):
        return ["AI"]

    async def fake_classify_entry_readonly(title, summary, *, category_names):
        return {"category": "新赛道", "tags": ["new"], "is_new_category": True, "confidence": 0.8}

    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", fake_get_active_category_names)
    monkeypatch.setattr(content_pipeline, "classify_entry_readonly", fake_classify_entry_readonly)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="New Category Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            await db.commit()

            item = await db.scalar(select(ContentItem))
            category = await db.scalar(select(Category).where(Category.name == "新赛道"))

        assert stats == {"fetched": 1, "new": 1, "duplicates": 0}
        assert item is not None
        assert item.category == "新赛道"
        assert category is not None
        assert category.is_auto_created is True
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_ingest_persists_content_before_classifier_failure(monkeypatch):
    class FakeScraper:
        def __init__(self, source_url, source_config):
            self.source_url = source_url
            self.source_config = source_config

        async def fetch(self, client):
            return [
                {
                    "title": "durable before LLM",
                    "url": "https://example.com/durable-before-llm",
                    "summary": "This item must survive a classifier outage.",
                }
            ]

    async def classifier_outage(title, summary, *, category_names):
        raise RuntimeError("classifier unavailable")

    async def category_names(db):
        return ["AI"]

    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda source_type: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", category_names)
    monkeypatch.setattr(content_pipeline, "classify_entry_readonly", classifier_outage)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        async with session_factory() as db:
            source = Source(
                id=1,
                name="Durable Example",
                url="https://example.com/feed",
                source_type=SourceType.RSS,
                enabled=True,
            )
            db.add(source)
            await db.commit()

            stats = await content_pipeline.ingest_from_source(source, db)
            row = await db.scalar(select(ContentItem))

        assert stats == {"fetched": 1, "new": 1, "duplicates": 0}
        assert row is not None
        assert row.status == ContentStatus.PENDING
        assert row.category is None
    finally:
        await engine.dispose()
