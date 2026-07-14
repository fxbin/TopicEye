from datetime import datetime
import time

from app.services.content_list_cache import ContentListCacheParams, invalidate_content_list_cache
from app.services.content_read_cache import invalidate_content_read_caches
from app.services.json_cache import get_cached_json, invalidate_json_cache, set_cached_json
from app.services.llm.model_list_cache import MODEL_LIST_CACHE_KEY, invalidate_model_list_cache
from app.services.scoring_flow import (
    build_empty_payload,
    cache_payload,
    get_cached_scoring_flow_json,
    invalidate_scoring_flow_cache,
)
from app.services.source_cache import SourceListCacheParams, invalidate_source_list_cache
from app.services.source_read_cache import invalidate_source_read_caches
from app.services.stats_cache import (
    STATS_CACHE_PREFIX,
    invalidate_novel_platform_stats_cache,
    invalidate_stats_cache,
)
from app.services.today_picks_cache import TodayPicksCacheParams, invalidate_today_picks_cache
from app.services.trending_cache import (
    TRENDING_CROSS_PLATFORM_CACHE_PREFIX,
    TRENDING_LIST_CACHE_PREFIX,
    TRENDING_PERSISTENT_CACHE_PREFIX,
    TRENDING_SOURCES_CACHE_KEY,
    invalidate_trending_cache,
)


def test_json_cache_hit_expire_and_prefix_invalidate():
    invalidate_json_cache()

    content = set_cached_json("perf:a", {"created_at": datetime(2026, 1, 2, 3, 4, 5), "value": "中文"})
    assert b"2026-01-02T03:04:05" in content
    assert "中文".encode() in content

    cached = get_cached_json("perf:a", ttl_seconds=10)
    assert cached is not None
    cached_content, age_seconds = cached
    assert cached_content == content
    assert age_seconds >= 0

    assert get_cached_json("perf:a", ttl_seconds=0) is None

    set_cached_json("perf:a", {"value": 1})
    set_cached_json("other:a", {"value": 2})
    invalidate_json_cache("perf:")
    assert get_cached_json("perf:a", ttl_seconds=10) is None
    assert get_cached_json("other:a", ttl_seconds=10) is not None

    invalidate_json_cache()
    assert get_cached_json("other:a", ttl_seconds=10) is None


def test_json_cache_respects_short_ttl():
    invalidate_json_cache()
    set_cached_json("ttl:test", {"value": 1})
    time.sleep(0.002)
    assert get_cached_json("ttl:test", ttl_seconds=0.001) is None


def test_content_list_cache_key_and_invalidation():
    invalidate_json_cache()
    params = ContentListCacheParams(
        page=1,
        page_size=50,
        hours=48,
    )
    key = params.key
    assert key == (
        "contents:list:page=1&page_size=50&include_trend_sources=0&sort_by=created_at&sort_order=desc&user_id=&hours=48"
    )

    set_cached_json(key, {"items": [], "total": 0})
    set_cached_json("contents:favorites:list:1:20", {"items": []})
    invalidate_content_list_cache()

    assert get_cached_json(key, ttl_seconds=10) is None
    assert get_cached_json("contents:favorites:list:1:20", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_today_picks_cache_key_and_invalidation():
    invalidate_json_cache()
    params = TodayPicksCacheParams(hours=48, category="AI", limit=80)
    key = params.key
    assert key == "contents:today-picks:hours=48&category=AI&limit=80&user_id="
    assert TodayPicksCacheParams(hours=48, category="AI", limit=80, user_id=42).key == (
        "contents:today-picks:hours=48&category=AI&limit=80&user_id=42"
    )

    set_cached_json(key, {"items": [], "total": 0})
    set_cached_json("contents:list:example", {"items": []})
    invalidate_today_picks_cache()

    assert get_cached_json(key, ttl_seconds=10) is None
    assert get_cached_json("contents:list:example", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_source_list_cache_key_and_invalidation():
    invalidate_json_cache()
    params = SourceListCacheParams(page=1, page_size=20, enabled=True, keyword="AI")
    key = params.key
    assert key == "sources:list:page=1&page_size=20&enabled=1&keyword=AI"

    set_cached_json(key, {"items": [], "total": 0})
    set_cached_json("contents:list:example", {"items": []})
    invalidate_source_list_cache()

    assert get_cached_json(key, ttl_seconds=10) is None
    assert get_cached_json("contents:list:example", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_source_read_cache_invalidation_covers_source_derived_stats():
    invalidate_json_cache()
    params = SourceListCacheParams(page=1, page_size=20)
    set_cached_json(params.key, {"items": [], "total": 0})
    set_cached_json("stats:source-distribution:7", {"sources": []})
    set_cached_json("stats:dashboard:7", {"kpi": {}})
    set_cached_json("contents:list:example", {"items": []})

    invalidate_source_read_caches()

    assert get_cached_json(params.key, ttl_seconds=10) is None
    assert get_cached_json("stats:source-distribution:7", ttl_seconds=10) is None
    assert get_cached_json("stats:dashboard:7", ttl_seconds=10) is None
    assert get_cached_json("contents:list:example", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_content_read_cache_invalidation_covers_content_derived_views():
    invalidate_json_cache()
    invalidate_scoring_flow_cache()
    set_cached_json("contents:list:example", {"items": []})
    set_cached_json("contents:today-picks:hours=48", {"items": []})
    set_cached_json("contents:favorites:list:1:20", {"items": []})
    set_cached_json("stats:overview:7", {"total": 1})
    set_cached_json("stats:dashboard:7", {"kpi": {}})
    cache_payload(
        (48, 160, 80, None),
        build_empty_payload(
            hours=48,
            analyzed_total=0,
            window_total=0,
            ignored_count=0,
            limit=160,
            sample_limit=80,
        ),
    )

    invalidate_content_read_caches()

    assert get_cached_json("contents:list:example", ttl_seconds=10) is None
    assert get_cached_json("contents:today-picks:hours=48", ttl_seconds=10) is None
    assert get_cached_json("stats:overview:7", ttl_seconds=10) is None
    assert get_cached_json("stats:dashboard:7", ttl_seconds=10) is None
    assert get_cached_scoring_flow_json(hours=48, limit=160) is None
    assert get_cached_json("contents:favorites:list:1:20", ttl_seconds=10) is not None
    invalidate_json_cache()
    invalidate_scoring_flow_cache()


def test_stats_cache_invalidation_is_scoped():
    invalidate_json_cache()
    set_cached_json(f"{STATS_CACHE_PREFIX}overview:7", {"total": 1})
    set_cached_json(f"{STATS_CACHE_PREFIX}dashboard:7", {"kpi": {}})
    set_cached_json("contents:list:example", {"items": []})

    invalidate_stats_cache()

    assert get_cached_json("stats:overview:7", ttl_seconds=10) is None
    assert get_cached_json("stats:dashboard:7", ttl_seconds=10) is None
    assert get_cached_json("contents:list:example", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_novel_platform_stats_cache_invalidation_is_scoped():
    invalidate_json_cache()
    set_cached_json("stats:novel-platforms", {"platforms": []})
    set_cached_json("stats:dashboard:7", {"platforms": []})
    set_cached_json("stats:dashboard:30", {"platforms": []})
    set_cached_json("stats:overview:7", {"total": 1})
    set_cached_json("stats:source-distribution:7", {"sources": []})

    invalidate_novel_platform_stats_cache()

    assert get_cached_json("stats:novel-platforms", ttl_seconds=10) is None
    assert get_cached_json("stats:dashboard:7", ttl_seconds=10) is None
    assert get_cached_json("stats:dashboard:30", ttl_seconds=10) is None
    assert get_cached_json("stats:overview:7", ttl_seconds=10) is not None
    assert get_cached_json("stats:source-distribution:7", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_model_list_cache_invalidation_is_scoped():
    invalidate_json_cache()
    set_cached_json(MODEL_LIST_CACHE_KEY, {"models": [], "total": 0})
    set_cached_json("models:usage:summary", {"total": {"calls": 1}})

    invalidate_model_list_cache()

    assert get_cached_json(MODEL_LIST_CACHE_KEY, ttl_seconds=10) is None
    assert get_cached_json("models:usage:summary", ttl_seconds=10) is not None
    invalidate_json_cache()


def test_trending_cache_invalidation_is_scoped():
    invalidate_json_cache()
    set_cached_json(f"{TRENDING_LIST_CACHE_PREFIX}limit=50", [{"title": "hot"}])
    set_cached_json(TRENDING_SOURCES_CACHE_KEY, [{"source": "weibo"}])
    set_cached_json(f"{TRENDING_CROSS_PLATFORM_CACHE_PREFIX}min_resonance=2&limit=50", {"clusters": []})
    set_cached_json(f"{TRENDING_PERSISTENT_CACHE_PREFIX}min_days=2&min_sources=1&days_back=7", {"topics": []})
    set_cached_json("contents:list:example", {"items": []})

    invalidate_trending_cache()

    assert get_cached_json(f"{TRENDING_LIST_CACHE_PREFIX}limit=50", ttl_seconds=10) is None
    assert get_cached_json(TRENDING_SOURCES_CACHE_KEY, ttl_seconds=10) is None
    assert get_cached_json(f"{TRENDING_CROSS_PLATFORM_CACHE_PREFIX}min_resonance=2&limit=50", ttl_seconds=10) is None
    assert (
        get_cached_json(f"{TRENDING_PERSISTENT_CACHE_PREFIX}min_days=2&min_sources=1&days_back=7", ttl_seconds=10)
        is None
    )
    assert get_cached_json("contents:list:example", ttl_seconds=10) is not None
    invalidate_json_cache()
