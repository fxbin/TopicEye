from datetime import UTC, date, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceStatus, SourceType
from app.models.trending import TrendingCategory, TrendingItem, TrendingSnapshot, TrendingSource
from app.services import cache_warmup
from app.services.content_list_cache import home_content_list_cache_params
from app.services.json_cache import get_cached_json, invalidate_json_cache
from app.services.scoring_flow import (
    SCORING_FLOW_WARMUP_TARGETS,
    get_cached_scoring_flow_json,
    invalidate_scoring_flow_cache,
)
from app.services.source_cache import default_source_list_cache_params
from app.services.today_picks_cache import default_today_picks_cache_params

STATS_WORKSPACE_CACHE_KEYS = {
    "stats:overview:30",
    "stats:source-distribution:30",
    "stats:category-distribution:30",
    "stats:daily-trend:30",
    "stats:novel-platforms",
    "stats:dashboard:30",
}

TRENDING_WORKSPACE_CACHE_KEYS = {
    "trending:list:limit=200",
    "trending:sources",
    "trending:cross-platform:min_resonance=2&limit=50",
    "trending:persistent:min_days=2&min_sources=1&days_back=7",
}


async def seed_cache_warmup_fixture(session_factory) -> None:
    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type=SourceType.RSS,
                url="https://example.com/rss.xml",
                category="AI",
                status=SourceStatus.ACTIVE,
                enabled=True,
                sort_order=10,
            )
        )
        db.add(
            ContentItem(
                id=1,
                title="测试选题",
                url="https://example.com/topic",
                source_id=1,
                source_name="测试信源",
                source_type="RSS",
                category="AI",
                status=ContentStatus.ANALYZED,
                is_favorited=True,
                crawled_at=datetime.now(UTC),
            )
        )
        db.add(
            AiAnalysis(
                content_id=1,
                curation_score=82,
                info_density=75,
                actionability=70,
                source_weight=80,
                quality_score=78,
                hot_score=65,
                freshness_score=90,
                creator_score=72,
                viral_score=61,
                risk_score=15,
                recommendation="适合作为创作者选题观察样本",
            )
        )
        db.add(
            TrendingItem(
                id=1,
                source=TrendingSource.WEIBO,
                category=TrendingCategory.HOT,
                rank=1,
                title="AI 产品趋势测试样本",
                url="https://example.com/trending/ai",
                hot_value=1200,
                hot_value_raw="1200",
                trend="up",
                batch_id="test-batch",
            )
        )
        today = date.today()
        for offset in (1, 0):
            db.add(
                TrendingSnapshot(
                    snapshot_date=today - timedelta(days=offset),
                    snapshot_hour=8,
                    source=TrendingSource.WEIBO,
                    category=TrendingCategory.HOT.value,
                    items=[
                        {
                            "title": "AI 产品趋势测试样本",
                            "rank": offset + 1,
                            "hot_value": 1200,
                        }
                    ],
                    total_count=1,
                )
            )
        await db.commit()


@pytest_asyncio.fixture
async def cache_warmup_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    invalidate_json_cache()
    invalidate_scoring_flow_cache()
    monkeypatch.setattr(cache_warmup, "async_session", session_factory)
    await seed_cache_warmup_fixture(session_factory)

    yield session_factory

    invalidate_json_cache()
    invalidate_scoring_flow_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_warmup_read_caches_populates_hot_read_cache_keys(cache_warmup_session):
    result = await cache_warmup.warmup_read_caches()

    expected_warmed = {
        "sources:list:1:20",
        "contents:list:1:40:24",
        "contents:today-picks:hours=24&limit=40",
        "contents:favorites:list:1:20",
    }
    expected_warmed.update(STATS_WORKSPACE_CACHE_KEYS)
    expected_warmed.update(TRENDING_WORKSPACE_CACHE_KEYS)
    expected_warmed.update(f"scoring-flow:{hours}:{limit}" for hours, limit in SCORING_FLOW_WARMUP_TARGETS)
    assert set(result["warmed"]) == expected_warmed
    assert result["errors"] == []
    ttl = settings.READ_CACHE_TTL_SECONDS
    assert get_cached_json(default_source_list_cache_params().key, ttl_seconds=ttl) is not None
    assert get_cached_json(home_content_list_cache_params().key, ttl_seconds=ttl) is not None
    assert get_cached_json(default_today_picks_cache_params().key, ttl_seconds=ttl) is not None
    assert get_cached_json("contents:favorites:list:1:20", ttl_seconds=ttl) is not None
    for key in STATS_WORKSPACE_CACHE_KEYS:
        assert get_cached_json(key, ttl_seconds=ttl) is not None
    for key in TRENDING_WORKSPACE_CACHE_KEYS:
        assert get_cached_json(key, ttl_seconds=ttl) is not None
    for hours, limit in SCORING_FLOW_WARMUP_TARGETS:
        assert get_cached_scoring_flow_json(hours=hours, limit=limit) is not None


@pytest.mark.asyncio
async def test_warmup_startup_critical_caches_populates_scoring_flow(cache_warmup_session):
    result = await cache_warmup.warmup_startup_critical_caches()

    expected_warmed = {f"scoring-flow:{hours}:{limit}" for hours, limit in SCORING_FLOW_WARMUP_TARGETS}
    expected_warmed.update(STATS_WORKSPACE_CACHE_KEYS)
    expected_warmed.update(TRENDING_WORKSPACE_CACHE_KEYS)
    assert set(result["warmed"]) == expected_warmed
    assert result["errors"] == []
    ttl = settings.READ_CACHE_TTL_SECONDS
    for hours, limit in SCORING_FLOW_WARMUP_TARGETS:
        assert get_cached_scoring_flow_json(hours=hours, limit=limit) is not None
    for key in STATS_WORKSPACE_CACHE_KEYS:
        assert get_cached_json(key, ttl_seconds=ttl) is not None
    for key in TRENDING_WORKSPACE_CACHE_KEYS:
        assert get_cached_json(key, ttl_seconds=ttl) is not None


@pytest.mark.asyncio
async def test_warmup_read_caches_can_skip_scoring_flow(cache_warmup_session):
    result = await cache_warmup.warmup_read_caches(include_scoring_flow=False)

    assert "sources:list:1:20" in result["warmed"]
    assert "contents:list:1:40:24" in result["warmed"]
    assert all(not label.startswith("scoring-flow:") for label in result["warmed"])
    assert result["errors"] == []
    for hours, limit in SCORING_FLOW_WARMUP_TARGETS:
        assert get_cached_scoring_flow_json(hours=hours, limit=limit) is None


@pytest.mark.asyncio
async def test_warmup_read_caches_can_skip_stats_workspace(cache_warmup_session):
    result = await cache_warmup.warmup_read_caches(include_scoring_flow=False, include_stats=False)

    assert "sources:list:1:20" in result["warmed"]
    assert "contents:list:1:40:24" in result["warmed"]
    assert all(not label.startswith("stats:") for label in result["warmed"])
    assert result["errors"] == []
    ttl = settings.READ_CACHE_TTL_SECONDS
    for key in STATS_WORKSPACE_CACHE_KEYS:
        assert get_cached_json(key, ttl_seconds=ttl) is None
