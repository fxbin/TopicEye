import time
from collections.abc import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import auth as auth_api, contents as contents_api
from app.core.database import Base
from app.services.auth_service import create_session, create_user
from app.services.scoring_engine import ScoreBreakdown, ScoringInput
from app.services.scoring_flow import (
    _cache_and_return,
    build_diagnostics,
    build_empty_payload,
    build_sample_payload,
    build_scoring_config_summary,
    build_stage_counts,
    debug_window_hours,
    get_cached_scoring_flow_json,
    invalidate_scoring_flow_cache,
)


class _DummySession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _dummy_session_factory():
    return _DummySession()


def _breakdown(content_id: int, **overrides) -> ScoreBreakdown:
    data = {
        "content_id": content_id,
        "base_score": 70,
        "source_bonus": 0,
        "quality_factor": 1.0,
        "risk_factor": 1.0,
        "time_decay": 0.9,
        "diversity_factor": 1.0,
        "final_score": 70,
        "dimension_scores": {"info_density": 20},
        "selected": True,
        "threshold_used": 60,
    }
    data.update(overrides)
    return ScoreBreakdown(**data)


def _scoring_input(content_id: int) -> ScoringInput:
    return ScoringInput(content_id=content_id, title=f"item {content_id}", source_name="source")


class _Content:
    id = 1
    title = "候选内容"
    url = "https://example.com"
    source_name = "知乎"
    category = "AI"


class _RichContent:
    id = 1
    title = "可创作内容"
    url = "https://example.com/rich"
    source_name = "AIHOT"
    category = "AI"
    summary = "原始摘要"
    tags = ["备用标签"]
    is_favorited = True
    ai_summary = "AI 摘要"
    recommendation = "中文推荐理由"
    recommended_reason = "备用推荐理由"
    analysis_tags = {"primary": ["AI", "Grok"], "secondary": "远程办公"}
    creator_angles = {"angles": ["拆解岗位要求", "延展远程办公趋势"]}


def test_build_stage_counts_uses_consistent_funnel_keys():
    scored = [
        (_breakdown(1), _scoring_input(1)),
        (_breakdown(2, quality_factor=0.55, selected=False), _scoring_input(2)),
        (_breakdown(3, risk_factor=0.55, selected=False), _scoring_input(3)),
    ]

    stages = build_stage_counts(scored)

    assert [stage["key"] for stage in stages] == [
        "candidates",
        "quality",
        "risk",
        "freshness",
        "diversity",
        "selected",
    ]
    assert stages[0]["count"] == 3
    assert stages[1]["count"] == 2
    assert stages[-1]["count"] == 1


def test_build_stage_counts_treats_freshness_as_downrank_not_filter():
    scored = [
        (_breakdown(1, time_decay=0.3), _scoring_input(1)),
        (_breakdown(2, time_decay=0.9), _scoring_input(2)),
    ]

    stages = {stage["key"]: stage for stage in build_stage_counts(scored)}

    assert stages["risk"]["count"] == 2
    assert stages["freshness"]["count"] == 2
    assert stages["diversity"]["count"] == 2


def test_build_sample_payload_keeps_breakdown_and_feedback_fields():
    breakdown = _breakdown(1)
    scoring_input = _scoring_input(1)

    sample = build_sample_payload(
        breakdown,
        scoring_input,
        {1: _Content()},
        {1: 20.0},
    )

    assert sample["title"] == "候选内容"
    assert sample["source_name"] == "知乎"
    assert sample["feedback_score"] == 20.0
    assert sample["dimension_scores"] == {"info_density": 20}
    assert sample["summary"] is None
    assert sample["recommendation"] is None
    assert sample["tags"] == []
    assert sample["creator_angles"] == []
    assert sample["is_favorited"] is False


def test_build_sample_payload_includes_creator_context_fields():
    breakdown = _breakdown(1)
    scoring_input = _scoring_input(1)

    sample = build_sample_payload(
        breakdown,
        scoring_input,
        {1: _RichContent()},
        {1: 20.0},
    )

    assert sample["summary"] == "AI 摘要"
    assert sample["recommendation"] == "中文推荐理由"
    assert sample["tags"] == ["AI", "Grok", "远程办公"]
    assert sample["creator_angles"] == ["拆解岗位要求", "延展远程办公趋势"]
    assert sample["is_favorited"] is True


def test_build_diagnostics_explains_empty_window():
    diagnostics = build_diagnostics(
        analyzed_total=12,
        window_total=0,
        loaded_count=0,
        scoring_input_count=0,
        scored_count=0,
        ignored_count=3,
        limit=160,
        sample_limit=80,
        window_counts=[
            {"hours": 24, "count": 0},
            {"hours": 48, "count": 0},
            {"hours": 168, "count": 12},
            {"hours": 720, "count": 12},
        ],
    )

    assert diagnostics["empty_reason"] == "no_content_in_window"
    assert diagnostics["analyzed_total"] == 12
    assert diagnostics["ignored_count"] == 3
    assert diagnostics["candidate_limit"] == 160
    assert diagnostics["recommended_hours"] == 168
    assert diagnostics["window_options"][2] == {"hours": 168, "count": 12}


def test_debug_window_hours_keeps_default_windows_without_custom_request():
    assert debug_window_hours() == (24, 48, 168, 720)


def test_debug_window_hours_includes_custom_request_once_and_sorted():
    assert debug_window_hours(96) == (24, 48, 96, 168, 720)
    assert debug_window_hours(48) == (24, 48, 168, 720)


def test_build_diagnostics_explains_collected_pending_analysis():
    diagnostics = build_diagnostics(
        analyzed_total=1141,
        window_total=0,
        collected_window_total=1485,
        loaded_count=0,
        scoring_input_count=0,
        scored_count=0,
        ignored_count=0,
        limit=160,
        sample_limit=80,
        window_counts=[
            {"hours": 24, "count": 0},
            {"hours": 48, "count": 0},
            {"hours": 168, "count": 1141},
            {"hours": 720, "count": 1141},
        ],
        collected_window_counts=[
            {"hours": 24, "count": 1485},
            {"hours": 48, "count": 1485},
            {"hours": 168, "count": 1485},
            {"hours": 720, "count": 1485},
        ],
    )

    assert diagnostics["empty_reason"] == "collected_not_analyzed"
    assert diagnostics["collected_window_total"] == 1485
    assert diagnostics["pending_analysis_total"] == 1485
    assert diagnostics["collected_window_options"][0] == {"hours": 24, "count": 1485}


def test_build_empty_payload_keeps_diagnostics_and_empty_collections():
    payload = build_empty_payload(
        hours=48,
        analyzed_total=12,
        window_total=0,
        ignored_count=1,
        limit=160,
        sample_limit=80,
    )

    assert payload["total"] == 0
    assert payload["scored"] == 0
    assert payload["diagnostics"]["empty_reason"] == "no_content_in_window"
    assert payload["diagnostics"]["analyzed_total"] == 12
    assert payload["diagnostics"]["window_options"] == []
    assert payload["stages"][0]["key"] == "candidates"
    assert payload["samples"] == []
    assert payload["category_mix"] == []
    assert payload["source_mix"] == []


def test_build_scoring_config_summary_exposes_readonly_thresholds():
    config = build_scoring_config_summary()

    assert config["curation_mode"] in {"percentile", "fixed"}
    assert "curation_threshold" in config
    assert "risk_threshold" in config
    assert "quality_gate_floor" in config


def test_scoring_flow_cache_can_be_invalidated():
    invalidate_scoring_flow_cache()

    _cache_and_return(
        48,
        160,
        80,
        None,
        build_empty_payload(
            hours=48,
            analyzed_total=0,
            window_total=0,
            ignored_count=0,
            limit=160,
            sample_limit=80,
        ),
    )

    assert get_cached_scoring_flow_json(hours=48, limit=160) is not None
    invalidate_scoring_flow_cache()
    assert get_cached_scoring_flow_json(hours=48, limit=160) is None


def test_scoring_flow_cache_uses_explicit_invalidation():
    invalidate_scoring_flow_cache()

    _cache_and_return(
        24,
        160,
        80,
        None,
        build_empty_payload(
            hours=24,
            analyzed_total=0,
            window_total=0,
            ignored_count=0,
            limit=160,
            sample_limit=80,
        ),
    )
    time.sleep(0.002)

    cached = get_cached_scoring_flow_json(hours=24, limit=160)

    assert cached is not None
    content, age_seconds = cached
    assert age_seconds > 0
    assert b'"mode":"invalidation"' in content
    invalidate_scoring_flow_cache()


@pytest.mark.asyncio
async def test_scoring_flow_api_cache_headers_and_503(monkeypatch):
    invalidate_scoring_flow_cache()
    monkeypatch.setattr(contents_api, "async_session", _dummy_session_factory)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="algorithm-user@example.com", password="Password123", role="user")
        token, _session = await create_session(db, user)
        await db.commit()

    app = FastAPI()
    app.include_router(contents_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    app.dependency_overrides[auth_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    calls = {"count": 0}

    async def fake_build_scoring_flow_payload(db, *, hours, limit, visible_user_id=None):
        calls["count"] += 1
        return _cache_and_return(
            hours,
            limit,
            80,
            visible_user_id,
            build_empty_payload(
                hours=hours,
                analyzed_total=0,
                window_total=0,
                ignored_count=0,
                limit=limit,
                sample_limit=80,
            ),
        )

    monkeypatch.setattr(contents_api, "build_scoring_flow_payload", fake_build_scoring_flow_payload)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        anonymous = await client.get("/contents/scoring-flow?hours=24&limit=160")
        first = await client.get(
            "/contents/scoring-flow?hours=24&limit=160",
            headers={"Authorization": f"Bearer {token}"},
        )
        second = await client.get(
            "/contents/scoring-flow?hours=24&limit=160",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert anonymous.status_code == 401
    assert first.status_code == 200
    assert first.headers["x-scoring-flow-cache"] == "MISS"
    assert first.json()["cache"]["hit"] is False
    assert second.status_code == 200
    assert second.headers["x-scoring-flow-cache"].startswith("HIT")
    assert second.json()["cache"]["hit"] is True
    assert calls["count"] == 1

    invalidate_scoring_flow_cache()

    async def fail_build_scoring_flow_payload(db, *, hours, limit, visible_user_id=None):
        raise RuntimeError("scoring flow failed")

    monkeypatch.setattr(contents_api, "build_scoring_flow_payload", fail_build_scoring_flow_payload)

    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        failed = await client.get(
            "/contents/scoring-flow?hours=24&limit=160",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert failed.status_code == 503
    assert failed.json()["detail"] == "Scoring flow unavailable"
    invalidate_scoring_flow_cache()
    await engine.dispose()
