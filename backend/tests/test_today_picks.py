import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app.api.v1 import contents as contents_api
from app.api.v1 import auth as auth_api
from app.repositories.content_repo import ContentRepo
from app.services import today_picks
from app.services.json_cache import invalidate_json_cache
from app.services.scoring_engine import ScoringInput, score_items


class FailingSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def execute(self, *args, **kwargs):
        raise AssertionError("today-picks should not query SQLAlchemy for analytical reads")


def _failing_session_factory():
    return FailingSession()


def _duckdb_rows():
    now = datetime.now(UTC)
    crawled_at = (now - timedelta(hours=2)).isoformat()
    return [
        {
            "id": 1,
            "title": "DuckDB 精选样本",
            "url": "https://example.com/pick",
            "source_id": 1,
            "source_name": "测试信源",
            "source_type": "RSS",
            "platform": "rss",
            "author": None,
            "published_at": crawled_at,
            "crawled_at": crawled_at,
            "content_hash": None,
            "summary": "原始摘要",
            "raw_content": None,
            "cover_url": None,
            "category": "AI",
            "tags": ["AI"],
            "language": "zh",
            "status": "analyzed",
            "is_favorited": False,
            "topic_id": 10,
            "duplicate_of": None,
            "similarity_score": 0.0,
            "created_at": crawled_at,
            "updated_at": crawled_at,
            "analysis_id": 101,
            "analysis_created_at": now.isoformat(),
            "quality_score": 80.0,
            "hot_score": 75.0,
            "freshness_score": 90.0,
            "creator_score": 86.0,
            "viral_score": 70.0,
            "risk_score": 15.0,
            "curation_score": 88.0,
            "info_density": 82.0,
            "actionability": 78.0,
            "recommended_reason": "值得写",
            "recommendation": "可以作为创作者选题",
            "ai_summary": "AI 分析摘要",
            "ai_tags": ["AI", "产品"],
            "enrichment_status": "pending",
            "enrichment": '{"why_matters":"测试"}',
            "analysis_source_weight": 72.0,
            "source_weight_db": 5,
            "feedback_score": 20.0,
            "adjusted_curation_score": 107.0,
        },
        {
            "id": 2,
            "title": "重复样本",
            "url": "https://example.com/duplicate",
            "source_id": 1,
            "source_name": "测试信源",
            "source_type": "RSS",
            "platform": "rss",
            "published_at": crawled_at,
            "crawled_at": crawled_at,
            "category": "AI",
            "status": "analyzed",
            "is_favorited": False,
            "topic_id": 10,
            "duplicate_of": 1,
            "analysis_id": 102,
            "analysis_created_at": now.isoformat(),
            "creator_score": 80.0,
            "risk_score": 10.0,
            "curation_score": 90.0,
            "analysis_source_weight": 50.0,
            "source_weight_db": 3,
            "adjusted_curation_score": 90.0,
        },
    ]


def _duckdb_rows_with_weak_candidate():
    rows = _duckdb_rows()
    weak = dict(rows[0])
    weak.update(
        {
            "id": 3,
            "title": "低质量预筛样本",
            "url": "https://example.com/weak",
            "quality_score": 30.0,
            "info_density": 30.0,
            "actionability": 30.0,
            "creator_score": 30.0,
            "viral_score": 30.0,
            "curation_score": 70.0,
            "adjusted_curation_score": 90.0,
            "topic_id": 11,
            "duplicate_of": None,
        }
    )
    return [weak, *rows]


def _duckdb_rows_with_mid_risk_candidate():
    rows = _duckdb_rows()
    candidate = dict(rows[0])
    candidate.update(
        {
            "id": 4,
            "title": "统一风险门候选",
            "url": "https://example.com/mid-risk",
            "risk_score": 80.0,
            "topic_id": 12,
            "duplicate_of": None,
        }
    )
    return [candidate, *rows]


def _expected_breakdown_for_first_row():
    row = _duckdb_rows()[0]
    return score_items(
        [
            ScoringInput(
                content_id=row["id"],
                title=row["title"],
                category=row["category"],
                source_id=row["source_id"],
                source_name=row["source_name"],
                published_at=row["published_at"],
                crawled_at=row["crawled_at"],
                curation_score=row["curation_score"],
                info_density=row["info_density"],
                actionability=row["actionability"],
                source_weight=row["analysis_source_weight"],
                creator_score=row["creator_score"],
                viral_score=row["viral_score"],
                freshness_score=row["freshness_score"],
                quality_score=row["quality_score"],
                hot_score=row["hot_score"],
                risk_score=row["risk_score"],
                source_weight_db=row["source_weight_db"],
                feedback_score=row["feedback_score"],
            )
        ]
    )[0][0].to_dict()


@pytest.mark.asyncio
async def test_build_today_picks_uses_duckdb_payload_without_orm(monkeypatch):
    async def fail_list_for_today_picks(*args, **kwargs):
        raise AssertionError("ContentRepo.list_for_today_picks should not be used")

    monkeypatch.setattr(ContentRepo, "list_for_today_picks", fail_list_for_today_picks)
    monkeypatch.setattr(
        today_picks,
        "query_today_picks",
        lambda hours=48, category=None, limit=None, curation_threshold=55: _duckdb_rows(),
    )
    monkeypatch.setattr(
        today_picks,
        "query_topics",
        lambda: [{"id": 10, "name": "AI 话题", "summary": "摘要", "keywords": ["AI"], "best_score": 104.0}],
    )

    payload = await today_picks.build_today_picks(FailingSession(), category="AI", hours=48, limit=1)

    assert payload["total"] == 1
    assert payload["duplicates_hidden"] == 1
    assert payload["page_size"] == 1
    assert payload["topics"] == [
        {"id": 10, "name": "AI 话题", "summary": "摘要", "keywords": ["AI"], "best_score": 104.0}
    ]
    item = payload["items"][0]
    expected = _expected_breakdown_for_first_row()
    assert item["id"] == 1
    assert item["tags"] == ["AI"]
    assert item["analysis"]["id"] == 101
    assert item["analysis"]["tags"] == ["AI", "产品"]
    assert item["analysis"]["enrichment"] == {"why_matters": "测试"}
    assert item["analysis"]["adjusted_curation_score"] == expected["final_score"]
    assert item["analysis"]["score_breakdown"]["final_score"] == expected["final_score"]
    assert item["analysis"]["score_breakdown"]["dimension_scores"]["feedback_adjustment"] == 3.0
    assert item["analysis"]["score_breakdown"]["source_bonus"] == expected["source_bonus"]
    assert item["analysis"]["score_breakdown"]["quality_factor"] == expected["quality_factor"]
    assert item["analysis"]["score_breakdown"]["risk_factor"] == expected["risk_factor"]
    assert item["analysis"]["score_breakdown"]["time_decay"] == expected["time_decay"]


@pytest.mark.asyncio
async def test_build_today_picks_filters_prescreened_items_with_unified_scorer(monkeypatch):
    query_args = []

    def fake_query_today_picks(hours=48, category=None, limit=None, curation_threshold=55):
        query_args.append(
            {
                "hours": hours,
                "category": category,
                "limit": limit,
                "curation_threshold": curation_threshold,
            }
        )
        return _duckdb_rows_with_weak_candidate()

    monkeypatch.setattr(
        today_picks,
        "query_today_picks",
        fake_query_today_picks,
    )
    monkeypatch.setattr(today_picks, "query_topics", lambda: [])

    payload = await today_picks.build_today_picks(FailingSession(), hours=48)

    assert query_args[0]["curation_threshold"] == 0
    assert [item["id"] for item in payload["items"]] == [1]
    assert payload["total"] == 1


@pytest.mark.asyncio
async def test_build_today_picks_lets_unified_scorer_decide_mid_risk_candidates(monkeypatch):
    query_args = []

    def fake_query_today_picks(hours=48, category=None, limit=None, curation_threshold=55):
        query_args.append(
            {
                "curation_threshold": curation_threshold,
            }
        )
        return _duckdb_rows_with_mid_risk_candidate()

    monkeypatch.setattr(today_picks, "query_today_picks", fake_query_today_picks)
    monkeypatch.setattr(today_picks, "query_topics", lambda: [])

    payload = await today_picks.build_today_picks(FailingSession(), hours=48)

    assert query_args[0]["curation_threshold"] == 0
    assert [item["id"] for item in payload["items"]] == [1]
    assert payload["total"] == 1


@pytest.mark.asyncio
async def test_today_picks_api_cache_headers_and_duckdb_503(monkeypatch):
    invalidate_json_cache()
    monkeypatch.setattr(contents_api.settings, "READ_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(contents_api, "async_session", _failing_session_factory)

    app = FastAPI()
    app.include_router(contents_api.router)
    transport = httpx.ASGITransport(app=app)
    calls = {"count": 0}

    async def fake_build_today_picks(db, *, category=None, hours=48, limit=None):
        calls["count"] += 1
        return {"items": [], "total": 0, "duplicates_hidden": 0, "topics": [], "page": 1, "page_size": 0}

    monkeypatch.setattr("app.services.today_picks.build_today_picks", fake_build_today_picks)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        first = await client.get("/contents/today-picks?time_range=48h")
        second = await client.get("/contents/today-picks?time_range=48h")

    assert first.status_code == 200
    assert first.headers["x-analytics-backend"] == "duckdb"
    assert first.headers["x-today-picks-cache"] == "MISS"
    assert second.status_code == 200
    assert second.headers["x-analytics-backend"] == "duckdb"
    assert second.headers["x-today-picks-cache"].startswith("HIT")
    assert calls["count"] == 1

    invalidate_json_cache()

    async def fail_build_today_picks(db, *, category=None, hours=48, limit=None):
        raise RuntimeError("duckdb unavailable")

    monkeypatch.setattr("app.services.today_picks.build_today_picks", fail_build_today_picks)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        failed = await client.get("/contents/today-picks?time_range=24h")

    assert failed.status_code == 503
    assert json.loads(failed.text)["detail"] == "DuckDB analytical layer unavailable"
    invalidate_json_cache()


@pytest.mark.asyncio
async def test_today_picks_cache_and_build_are_user_scoped(monkeypatch):
    """Private-source picks must not reuse the anonymous or another user's cache."""
    invalidate_json_cache()
    monkeypatch.setattr(contents_api.settings, "READ_CACHE_TTL_SECONDS", 60)
    monkeypatch.setattr(contents_api, "async_session", _failing_session_factory)

    app = FastAPI()
    app.include_router(contents_api.router)
    transport = httpx.ASGITransport(app=app)
    calls: list[int | None] = []

    async def fake_build_today_picks(db, *, category=None, hours=48, limit=None, owner_user_id=None):
        calls.append(owner_user_id)
        return {
            "items": [{"id": owner_user_id or 0}],
            "total": 1,
            "duplicates_hidden": 0,
            "topics": [],
            "page": 1,
            "page_size": 1,
        }

    monkeypatch.setattr("app.services.today_picks.build_today_picks", fake_build_today_picks)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        public = await client.get("/contents/today-picks")
        app.dependency_overrides[auth_api.get_optional_current_user] = lambda: SimpleNamespace(id=7)
        user_first = await client.get("/contents/today-picks")
        user_second = await client.get("/contents/today-picks")

    assert public.json()["items"][0]["id"] == 0
    assert user_first.json()["items"][0]["id"] == 7
    assert user_first.headers["x-today-picks-cache"] == "MISS"
    assert user_second.headers["x-today-picks-cache"].startswith("HIT")
    assert calls == [None, 7]
    invalidate_json_cache()


def test_today_picks_scoring_input_preserves_zero_and_analysis_source_weight():
    row = _duckdb_rows()[0]
    row.update(
        {
            "info_density": 0,
            "actionability": 0,
            "analysis_source_weight": 0,
            "freshness_score": 0,
        }
    )

    scoring_input = today_picks._row_to_scoring_input(row)

    assert scoring_input.info_density == 0
    assert scoring_input.actionability == 0
    assert scoring_input.source_weight == 0
    assert scoring_input.freshness_score == 0


@pytest.mark.asyncio
async def test_build_today_picks_duckdb_unavailable_returns_empty_payload(monkeypatch, caplog):
    """DuckDB 抛错（host 解析失败、ATTACH 失败等）时，build_today_picks 不应
    向上抛异常，而应回退到空 payload 并记录带 stack trace 的 WARNING，让
    UI 看到"今日无数据"而不是 503/错误页，且运维能 grep 日志定位。
    """
    import logging

    def fail_query(**_kwargs):
        raise OSError("Unable to connect to Postgres at host=postgres: nodename nor servname provided")

    monkeypatch.setattr(today_picks, "query_today_picks", fail_query)
    # 防御性 patch：若 query_topics 误调成功路径也会被这里兜住
    monkeypatch.setattr(today_picks, "query_topics", fail_query)

    with caplog.at_level(logging.WARNING, logger="app.services.today_picks"):
        payload = await today_picks.build_today_picks(FailingSession(), hours=48, limit=20)

    assert payload == {
        "items": [],
        "total": 0,
        "duplicates_hidden": 0,
        "topics": [],
        "page": 1,
        "page_size": 0,
    }
    # 至少一条 WARNING 带 exc_info（即 stack trace 写进了日志）
    fallback_logs = [r for r in caplog.records if "today_picks" in r.message and "unavailable" in r.message]
    assert fallback_logs, "expected a fallback warning log"
    assert all(r.exc_info is not None for r in fallback_logs), "fallback log must include exc_info"
    invalidate_json_cache()


@pytest.mark.asyncio
async def test_build_today_picks_duckdb_failure_falls_back_to_oltp(monkeypatch):
    """DuckDB 失败时，build_today_picks 应走 OLTP fallback 返回真实数据。

    核心价值：本地开发 host=postgres 解析不到、ATTACH 失败时，UI 仍能看到
    选题，不只是空 payload。
    """
    from datetime import UTC, datetime, timedelta

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.models.analysis import AiAnalysis
    from app.models.content import ContentItem, ContentStatus
    from app.models.source import Source, SourceStatus, SourceType

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    crawled_at = now - timedelta(hours=2)
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        source = Source(
            name="测试信源",
            source_type=SourceType.RSS,
            url="https://example.com/feed",
            weight=5,
            status=SourceStatus.ACTIVE,
        )
        db.add(source)
        await db.flush()

        # 高分样本：应入选（curation_score 88、creator_score 86，最终 final > 55）
        db.add(
            ContentItem(
                title="高质量样本",
                url="https://example.com/pick-1",
                source_id=source.id,
                source_type=SourceType.RSS,
                crawled_at=crawled_at,
                published_at=crawled_at,
                category="AI",
                status=ContentStatus.ANALYZED,
                created_at=crawled_at,
                updated_at=crawled_at,
            )
        )
        await db.flush()
        # 重新查一遍拿到 id
        from sqlalchemy import select

        item = (await db.execute(select(ContentItem).order_by(ContentItem.id.desc()))).scalars().first()
        db.add(
            AiAnalysis(
                content_id=item.id,
                quality_score=80.0,
                hot_score=75.0,
                freshness_score=90.0,
                creator_score=86.0,
                viral_score=70.0,
                risk_score=15.0,
                curation_score=88.0,
                info_density=82.0,
                actionability=78.0,
                summary="AI 摘要",
                tags=["AI"],
                recommended_reason="值得写",
                recommendation="可作为创作者选题",
                source_weight=72.0,
                created_at=now,
            )
        )
        await db.commit()

    # DuckDB 路径强制失败
    def fail_query(**_kwargs):
        raise OSError("Unable to connect to Postgres at host=postgres")

    monkeypatch.setattr(today_picks, "query_today_picks", fail_query)
    monkeypatch.setattr(today_picks, "query_topics", fail_query)

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        payload = await today_picks.build_today_picks(db, hours=48, limit=20)

    await engine.dispose()
    invalidate_json_cache()

    # OLTP fallback 应返回真实数据，不再是空
    assert payload["total"] >= 1, f"OLTP fallback returned empty; payload={payload}"
    assert payload["page_size"] >= 1
    item_out = payload["items"][0]
    assert item_out["title"] == "高质量样本"
    assert item_out["source_name"] == "测试信源"
    assert item_out["analysis"]["curation_score"] == 88.0
    assert item_out["analysis"]["creator_score"] == 86.0


def test_score_rows_does_not_double_filter_with_today_picks_threshold():
    """回归:percentile 模式下被 score_items 选中的项不应再被硬阈值 55 误过滤。

    场景:3 天前抓的数据,time_decay_floor 0.3 导致 final_score 偏低(~20)。
    score_items 在 percentile 模式下(默认 P70)选 P70 及以上的项,实际阈值 ~18;
    之前 _score_rows 又加了 `final_score >= 55` 兜底,把 percentile 选出的 394 条
    全部过滤掉,today_picks 永远空。
    """
    from datetime import UTC, datetime, timedelta

    from app.services.scoring_engine import ScoringInput, score_items

    now = datetime.now(UTC)
    crawled_at = (now - timedelta(days=3)).isoformat()
    inputs = []
    for i in range(100):
        inputs.append(
            ScoringInput(
                content_id=i,
                title=f"样本 {i}",
                category="AI",
                source_id=1,
                source_name="test",
                published_at=crawled_at,
                crawled_at=crawled_at,
                curation_score=80.0,
                info_density=80.0,
                actionability=80.0,
                source_weight=72.0,
                creator_score=80.0,
                viral_score=70.0,
                risk_score=10.0,
                quality_score=80.0,
                hot_score=60.0,
                freshness_score=80.0,
                source_weight_db=3,
                feedback_score=0,
            )
        )
    scored = score_items(inputs)
    selected_in_engine = [bd for bd, _ in scored if bd.selected]
    assert len(selected_in_engine) > 0, "score_items 应在 percentile 模式选中一些项"

    # 关键:_score_rows 出来的结果数应该和 score_items 的 selected 数一致,
    # 不应该再被一个硬阈值 55 二次过滤
    rows = [
        {
            "id": i,
            "title": f"样本 {i}",
            "category": "AI",
            "source_id": 1,
            "source_name": "test",
            "source_type": "RSS",
            "published_at": crawled_at,
            "crawled_at": crawled_at,
            "curation_score": 80.0,
            "info_density": 80.0,
            "actionability": 80.0,
            "analysis_source_weight": 72.0,
            "creator_score": 80.0,
            "viral_score": 70.0,
            "risk_score": 10.0,
            "quality_score": 80.0,
            "hot_score": 60.0,
            "freshness_score": 80.0,
            "source_weight_db": 3,
            "feedback_score": 0,
            "duplicate_of": None,
        }
        for i in range(100)
    ]
    out = today_picks._score_rows(rows)
    assert len(out) == len(
        selected_in_engine
    ), f"_score_rows ({len(out)}) 不应再过滤掉 score_items 选中的 {len(selected_in_engine)} 条"


# ── OLTP fallback 口径对齐 DuckDB 的回归测试 ──────────────────────────


async def _seed_oltp_fixture(engine, *, extra_content=None, ignored_ids=(), feedback_rows=()):
    """Seed an in-memory OLTP DB with a source + content + analyses.

    ``extra_content``: list of dicts overriding ContentItem/AiAnalysis fields.
    ``ignored_ids``: content ids to mark ignored.
    ``feedback_rows``: list of (content_id, user_id, score_delta) tuples.
    Returns the list of created content ids.
    """
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.analysis import AiAnalysis
    from app.models.content import ContentItem, ContentStatus
    from app.models.feedback import UserFeedback
    from app.models.ignored import IgnoredItem
    from app.models.source import Source, SourceStatus, SourceType

    now = datetime.now(UTC)
    crawled_at = now - timedelta(hours=2)
    created_ids: list[int] = []
    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        source = Source(
            name="测试信源",
            source_type=SourceType.RSS,
            url="https://example.com/feed",
            weight=5,
            status=SourceStatus.ACTIVE,
        )
        db.add(source)
        await db.flush()

        specs = [
            {  # 高质量基线样本
                "title": "高质量样本",
                "url": "https://example.com/pick-1",
                "quality_score": 80.0,
                "creator_score": 86.0,
                "risk_score": 15.0,
                "curation_score": 88.0,
            }
        ]
        if extra_content:
            specs.extend(extra_content)

        for spec in specs:
            url = spec.get("url", f"https://example.com/c-{len(created_ids) + 1}")
            title = spec.get("title", f"样本 {len(created_ids) + 1}")
            content = ContentItem(
                title=title,
                url=url,
                source_id=source.id,
                source_type=SourceType.RSS,
                crawled_at=spec.get("crawled_at", crawled_at),
                published_at=spec.get("crawled_at", crawled_at),
                category=spec.get("category", "AI"),
                status=ContentStatus.ANALYZED,
                duplicate_of=spec.get("duplicate_of"),
                created_at=crawled_at,
                updated_at=crawled_at,
            )
            db.add(content)
            await db.flush()
            cid = content.id
            created_ids.append(cid)
            db.add(
                AiAnalysis(
                    content_id=cid,
                    quality_score=spec.get("quality_score", 80.0),
                    hot_score=spec.get("hot_score", 75.0),
                    freshness_score=spec.get("freshness_score", 90.0),
                    creator_score=spec.get("creator_score", 86.0),
                    viral_score=spec.get("viral_score", 70.0),
                    risk_score=spec.get("risk_score", 15.0),
                    curation_score=spec.get("curation_score", 88.0),
                    info_density=spec.get("info_density", 82.0),
                    actionability=spec.get("actionability", 78.0),
                    summary=spec.get("summary", "AI 摘要"),
                    tags=spec.get("tags", ["AI"]),
                    recommended_reason="值得写",
                    recommendation="可作为创作者选题",
                    source_weight=72.0,
                    created_at=now,
                )
            )

        for cid in ignored_ids:
            db.add(IgnoredItem(content_id=cid))
        for content_id, user_id, score_delta in feedback_rows:
            db.add(UserFeedback(content_id=content_id, user_id=user_id, score_delta=score_delta, feedback_type="like"))
        await db.commit()

    return created_ids


@pytest.mark.asyncio
async def test_fallback_risk_threshold_aligned_to_82(monkeypatch):
    """风险 60 的内容在旧 fallback（阈值 50）会被误杀；对齐到 82 后应保留。

    场景：risk_score=60，在 DuckDB 主路径（risk <= 82）能进、scorer 软降权后仍可入选；
    旧 fallback 用硬编码 50 会直接丢弃。
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ids = await _seed_oltp_fixture(
        engine,
        extra_content=[
            {"title": "中风险样本", "url": "https://example.com/mid-risk", "risk_score": 60.0},
        ],
    )
    mid_risk_id = ids[1]

    monkeypatch.setattr(today_picks, "query_today_picks", lambda **_k: (_ for _ in ()).throw(OSError("duckdb down")))
    monkeypatch.setattr(today_picks, "query_topics", lambda **_k: [])

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        rows = await today_picks._build_today_picks_via_oltp(db, hours=48, category=None, limit=None)

    await engine.dispose()
    row_ids = {row["id"] for row in rows}
    assert mid_risk_id in row_ids, "风险 60 的内容应保留（阈值对齐 82 后不被误杀）"
    assert all(row["risk_score"] <= 82 for row in rows)


@pytest.mark.asyncio
async def test_fallback_excludes_ignored_content(monkeypatch):
    """OLTP fallback 应剔除 ignored 内容（与 DuckDB IGNORED_CONTENT_CTE 口径一致）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ids = await _seed_oltp_fixture(
        engine,
        extra_content=[{"title": "应被忽略", "url": "https://example.com/ignored"}],
    )
    to_ignore = ids[1]
    # 单独插一条 ignored 记录
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.ignored import IgnoredItem

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        db.add(IgnoredItem(content_id=to_ignore))
        await db.commit()

    monkeypatch.setattr(today_picks, "query_today_picks", lambda **_k: (_ for _ in ()).throw(OSError("duckdb down")))
    monkeypatch.setattr(today_picks, "query_topics", lambda **_k: [])

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        rows = await today_picks._build_today_picks_via_oltp(db, hours=48, category=None, limit=None)

    await engine.dispose()
    row_ids = {row["id"] for row in rows}
    assert to_ignore not in row_ids, "ignored 内容应被 fallback 剔除"
    assert ids[0] in row_ids, "非 ignored 高质量样本应保留"


@pytest.mark.asyncio
async def test_fallback_aggregates_feedback_score(monkeypatch):
    """OLTP fallback 应聚合真实 feedback_score（不再硬编码 0）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    ids = await _seed_oltp_fixture(
        engine,
        feedback_rows=[(1, 100, 10.0), (1, 200, 20.0)],  # content_id=1，两用户合计 +30
    )
    # _seed_oltp_fixture 用自增 id，第一条 content id 通常是 1
    target_id = ids[0]

    monkeypatch.setattr(today_picks, "query_today_picks", lambda **_k: (_ for _ in ()).throw(OSError("duckdb down")))
    monkeypatch.setattr(today_picks, "query_topics", lambda **_k: [])

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        rows = await today_picks._build_today_picks_via_oltp(db, hours=48, category=None, limit=None)

    await engine.dispose()
    target_row = next(row for row in rows if row["id"] == target_id)
    assert target_row["feedback_score"] == 30.0, f"应聚合 +30，实际 {target_row['feedback_score']}"


@pytest.mark.asyncio
async def test_fallback_reads_real_duplicate_of(monkeypatch):
    """OLTP fallback 应读真实 duplicate_of 列并剔除重复（不再硬编码 None）。"""
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    canonical_id = 1  # 先占位，seed 后回填
    ids = await _seed_oltp_fixture(
        engine,
        extra_content=[
            {"title": "重复样本", "url": "https://example.com/dup", "duplicate_of": canonical_id},
        ],
    )
    canonical_id = ids[0]
    dup_id = ids[1]

    monkeypatch.setattr(today_picks, "query_today_picks", lambda **_k: (_ for _ in ()).throw(OSError("duckdb down")))
    monkeypatch.setattr(today_picks, "query_topics", lambda **_k: [])

    async with async_sessionmaker(engine, expire_on_commit=False)() as db:
        rows = await today_picks._build_today_picks_via_oltp(db, hours=48, category=None, limit=None)

    await engine.dispose()
    # fallback row dict 应携带真实 duplicate_of（而非硬编码 None）
    dup_row = next(row for row in rows if row["id"] == dup_id)
    assert dup_row["duplicate_of"] == canonical_id, "fallback 应读真实 duplicate_of 列"
    # _score_rows 应剔除重复项（duplicate_of is None 过滤）
    scored = today_picks._score_rows(rows)
    scored_ids = {row["id"] for _, row in scored}
    assert dup_id not in scored_ids, "重复项应被 _score_rows 剔除"
