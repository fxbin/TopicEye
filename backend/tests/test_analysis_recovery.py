# ruff: noqa: I001
import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.sql.selectable import Select

from app.api.v1 import analyses as analyses_api
from app.core.database import Base
from app.models.analysis import AiAnalysis
from app.models.analysis_job import AnalysisJobRecord
from app.models.content import ContentItem, ContentStatus
from app.models.metrics import ContentMetrics  # noqa: F401
from app.models.source import Source  # noqa: F401
from app.models.topic import TopicGroup  # noqa: F401
from app.repositories.content_repo import ANALYSIS_STALE_MINUTES, ContentRepo
from app.services import analysis, analysis_jobs
from app.services.analysis_jobs import (
    create_analysis_job,
    finish_analysis_job,
    get_analysis_job,
    mark_analysis_job_running,
    reset_analysis_jobs,
)
from app.services.scoring_flow import (
    build_empty_payload,
    _cache_and_return,
    get_cached_scoring_flow_json,
    invalidate_scoring_flow_cache,
)
from app import scheduler as scheduler_module
from app import _post_sync_pipeline as post_sync_pipeline_module


async def _session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, session_factory


@pytest.mark.asyncio
async def test_list_pending_for_analysis_filters_recent_pending_items():
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="旧待分析内容",
                    url="https://example.com/old",
                    status=ContentStatus.PENDING,
                    crawled_at=now - timedelta(hours=30),
                ),
                ContentItem(
                    id=2,
                    title="最近待分析内容",
                    url="https://example.com/recent",
                    status=ContentStatus.PENDING,
                    crawled_at=now - timedelta(hours=1),
                ),
                ContentItem(
                    id=3,
                    title="最近已分析内容",
                    url="https://example.com/analyzed",
                    status=ContentStatus.ANALYZED,
                    crawled_at=now,
                ),
                ContentItem(
                    id=4,
                    title="超时分析中内容",
                    url="https://example.com/stale-analyzing",
                    status=ContentStatus.ANALYZING,
                    crawled_at=now - timedelta(minutes=30),
                    updated_at=now - timedelta(minutes=ANALYSIS_STALE_MINUTES + 5),
                ),
                ContentItem(
                    id=5,
                    title="刚进入分析中的内容",
                    url="https://example.com/fresh-analyzing",
                    status=ContentStatus.ANALYZING,
                    crawled_at=now - timedelta(minutes=20),
                    updated_at=now,
                ),
                ContentItem(
                    id=6,
                    title="可重试失败内容",
                    url="https://example.com/retry-error",
                    status=ContentStatus.ERROR,
                    crawled_at=now - timedelta(minutes=10),
                    updated_at=now - timedelta(minutes=ANALYSIS_STALE_MINUTES + 5),
                ),
                ContentItem(
                    id=7,
                    title="刚失败内容",
                    url="https://example.com/fresh-error",
                    status=ContentStatus.ERROR,
                    crawled_at=now - timedelta(minutes=5),
                    updated_at=now,
                ),
                ContentItem(
                    id=8,
                    title="已跳过分析的最新内容",
                    url="https://example.com/skip-analysis",
                    status=ContentStatus.PENDING,
                    skip_analysis=True,
                    crawled_at=now,
                ),
            ]
        )
        await db.commit()

        pending = await ContentRepo(db).list_pending_for_analysis(limit=10, hours=24)

    assert [item.id for item in pending] == [6, 4, 2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_pending_analysis_ids_marks_items_analyzing_before_workers_run():
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="待认领内容",
                url="https://example.com/claim-pending",
                status=ContentStatus.PENDING,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.commit()

        claimed_ids = await ContentRepo(db).claim_pending_analysis_ids(limit=10, hours=24)
        await db.commit()

    async with session_factory() as db:
        second_claim = await ContentRepo(db).claim_pending_analysis_ids(limit=10, hours=24)
        content = await db.get(ContentItem, 1)

    assert claimed_ids == [1]
    assert second_claim == []
    assert content.status == ContentStatus.ANALYZING
    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_pending_analysis_ids_retries_sqlite_write_lock(monkeypatch):
    engine, session_factory = await _session_factory()
    calls = {"begin": 0}

    async def flaky_begin_immediate(_db):
        calls["begin"] += 1
        if calls["begin"] == 1:
            raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    monkeypatch.setattr("app.repositories.content_repo.begin_immediate_for_sqlite", flaky_begin_immediate)

    # sqlite write lock 重试路径: 必须 is_sqlite=True 才会进 begin_immediate 分支
    class FakeProfile:
        is_sqlite = True
        is_postgresql = False

    monkeypatch.setattr("app.repositories.content_repo.database_profile", FakeProfile())

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="锁重试认领内容",
                url="https://example.com/claim-lock-retry",
                status=ContentStatus.PENDING,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.commit()

        claimed_ids = await ContentRepo(db).claim_pending_analysis_ids(limit=10, hours=24)
        await db.commit()

        content = await db.get(ContentItem, 1)

    assert calls["begin"] == 2
    assert claimed_ids == [1]
    assert content.status == ContentStatus.ANALYZING
    await engine.dispose()


@pytest.mark.asyncio
async def test_claim_pending_analysis_ids_uses_skip_locked_for_postgresql(monkeypatch):
    engine, session_factory = await _session_factory()
    calls = {"skip_locked": 0}

    class FakeProfile:
        is_sqlite = False
        is_postgresql = True

    monkeypatch.setattr("app.repositories.content_repo.database_profile", FakeProfile())
    original_with_for_update = Select.with_for_update

    def with_for_update_spy(self, *args, **kwargs):
        if kwargs.get("skip_locked") is True:
            calls["skip_locked"] += 1
        return original_with_for_update(self, *args, **kwargs)

    monkeypatch.setattr(Select, "with_for_update", with_for_update_spy)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="Postgres 并发认领一",
                    url="https://example.com/postgres-claim-1",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=2,
                    title="Postgres 并发认领二",
                    url="https://example.com/postgres-claim-2",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC) - timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        repo = ContentRepo(db)
        claimed_ids = await repo.claim_pending_analysis_ids(limit=10, hours=24)
        await db.commit()

    assert calls["skip_locked"] == 1
    assert claimed_ids == [1, 2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_pending_defaults_to_background_queue(monkeypatch):
    await reset_analysis_jobs()

    async def fail_if_sync_analysis_runs(*args, **kwargs):
        raise AssertionError("pending endpoint should not analyze synchronously by default")

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fail_if_sync_analysis_runs)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="最近待后台分析内容",
                url="https://example.com/background-queue",
                status=ContentStatus.PENDING,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.commit()

        background_tasks = BackgroundTasks()
        result = await analyses_api.analyze_all_pending(
            limit=10,
            hours=24,
            sync=False,
            background_tasks=background_tasks,
            db=db,
        )

    assert result["mode"] == "background"
    assert result["queued_ids"] == [1]
    assert result["analyzed_ids"] == []
    assert result["job_id"]
    assert result["hours"] == 24
    assert len(background_tasks.tasks) == 1

    job = await get_analysis_job(result["job_id"])
    assert job["status"] == "QUEUED"
    assert job["queued_ids"] == [1]
    assert job["pending_ids"] == [1]

    async with session_factory() as db:
        content = await db.get(ContentItem, 1)
    assert content.status == ContentStatus.ANALYZING

    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analyze_pending_deduplicates_inflight_background_jobs(monkeypatch):
    await reset_analysis_jobs()

    async def fail_if_sync_analysis_runs(*args, **kwargs):
        raise AssertionError("pending endpoint should not analyze synchronously by default")

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fail_if_sync_analysis_runs)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="重复提交的后台分析内容",
                url="https://example.com/background-queue-dedupe",
                status=ContentStatus.PENDING,
                crawled_at=datetime.now(UTC),
            )
        )
        await db.commit()

        first_tasks = BackgroundTasks()
        first = await analyses_api.analyze_all_pending(
            limit=10,
            hours=24,
            sync=False,
            background_tasks=first_tasks,
            db=db,
        )
        second_tasks = BackgroundTasks()
        second = await analyses_api.analyze_all_pending(
            limit=10,
            hours=24,
            sync=False,
            background_tasks=second_tasks,
            db=db,
        )

    assert first["queued_ids"] == [1]
    assert first["job_id"]
    assert len(first_tasks.tasks) == 1
    assert second["queued_ids"] == []
    assert second["skipped_inflight_ids"] == []
    assert second["job_id"] is None
    assert len(second_tasks.tasks) == 0

    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analysis_job_status_records_completion():
    await reset_analysis_jobs()
    job = await create_analysis_job([1, 2])

    await mark_analysis_job_running(job.job_id)
    await finish_analysis_job(job.job_id, analyzed_ids=[1], failed_ids=[2])

    status = await analyses_api.get_analysis_job_status(job.job_id)

    assert status["status"] == "PARTIAL"
    assert status["analyzed_ids"] == [1]
    assert status["failed_ids"] == [2]
    assert status["pending_ids"] == []
    assert status["started_at"] is not None
    assert status["finished_at"] is not None
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analysis_job_status_persists_for_memory_miss(monkeypatch):
    await reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(analysis_jobs, "async_session", session_factory)

    job = await create_analysis_job([1, 2, 2])
    await mark_analysis_job_running(job.job_id)
    await finish_analysis_job(job.job_id, analyzed_ids=[1], failed_ids=[2])

    async with session_factory() as db:
        record = await db.get(AnalysisJobRecord, job.job_id)

    assert record is not None
    assert record.status == "PARTIAL"
    assert record.content_ids == [1, 2]
    assert record.analyzed_ids == [1]
    assert record.failed_ids == [2]

    async with analysis_jobs._lock:
        analysis_jobs._jobs.clear()
        analysis_jobs._active_content_ids.clear()

    status = await get_analysis_job(job.job_id)

    assert status["status"] == "PARTIAL"
    assert status["queued_ids"] == [1, 2]
    assert status["analyzed_ids"] == [1]
    assert status["failed_ids"] == [2]
    assert status["pending_ids"] == []
    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analysis_job_snapshot_retries_sqlite_lock(monkeypatch):
    await reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    calls = {"begin": 0}

    async def flaky_begin_immediate(_db):
        calls["begin"] += 1
        if calls["begin"] == 1:
            raise OperationalError("BEGIN IMMEDIATE", {}, Exception("database is locked"))

    monkeypatch.setattr(analysis_jobs, "async_session", session_factory)
    monkeypatch.setattr(analysis_jobs, "begin_immediate_for_sqlite", flaky_begin_immediate)

    job = await create_analysis_job([1])

    async with session_factory() as db:
        record = await db.get(AnalysisJobRecord, job.job_id)

    assert calls["begin"] == 2
    assert record is not None
    assert record.status == "QUEUED"
    assert record.content_ids == [1]
    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_background_analysis_releases_failed_claims(monkeypatch):
    await reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(analyses_api, "async_session", session_factory)

    async def fake_concurrent(content_ids, **_kwargs):
        async with session_factory() as db:
            content = await db.get(ContentItem, 1)
            analysis_record = AiAnalysis(
                content_id=1,
                summary="后台已分析",
                curation_score=60,
            )
            db.add(analysis_record)
            content.status = ContentStatus.ANALYZED
            await db.commit()
        return [SimpleNamespace(content_id=1)]

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fake_concurrent)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="后台成功内容",
                    url="https://example.com/background-success",
                    status=ContentStatus.ANALYZING,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=2,
                    title="后台失败释放内容",
                    url="https://example.com/background-release-failed",
                    status=ContentStatus.ANALYZING,
                    crawled_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()

    job = await create_analysis_job([1, 2])
    await analyses_api._run_batch_background(job.job_id, [1, 2])

    async with session_factory() as db:
        statuses = {item.id: item.status for item in (await db.execute(select(ContentItem))).scalars().all()}
    job_status = await get_analysis_job(job.job_id)

    assert statuses == {
        1: ContentStatus.ANALYZED,
        2: ContentStatus.PENDING,
    }
    assert job_status["status"] == "PARTIAL"
    assert job_status["analyzed_ids"] == [1]
    assert job_status["failed_ids"] == [2]
    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_background_analysis_releases_claims_on_batch_exception(monkeypatch):
    await reset_analysis_jobs()
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(analyses_api, "async_session", session_factory)

    async def failing_concurrent(*_args, **_kwargs):
        raise RuntimeError("background worker crashed")

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", failing_concurrent)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="后台异常释放一",
                    url="https://example.com/background-exception-release-1",
                    status=ContentStatus.ANALYZING,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=2,
                    title="后台异常释放二",
                    url="https://example.com/background-exception-release-2",
                    status=ContentStatus.ANALYZING,
                    crawled_at=datetime.now(UTC),
                ),
            ]
        )
        await db.commit()

    job = await create_analysis_job([1, 2])

    with pytest.raises(RuntimeError):
        await analyses_api._run_batch_background(job.job_id, [1, 2])

    async with session_factory() as db:
        statuses = {item.id: item.status for item in (await db.execute(select(ContentItem))).scalars().all()}
    job_status = await get_analysis_job(job.job_id)

    assert statuses == {
        1: ContentStatus.PENDING,
        2: ContentStatus.PENDING,
    }
    assert job_status["status"] == "FAILED"
    assert job_status["failed_ids"] == [1, 2]
    assert "background worker crashed" in job_status["error_message"]
    await engine.dispose()
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analysis_job_inflight_ttl_releases_stuck_ids(monkeypatch):
    await reset_analysis_jobs()
    monkeypatch.setattr(analysis_jobs.settings, "ANALYSIS_JOB_INFLIGHT_TTL_SECONDS", 60)

    first = await create_analysis_job([1])
    first.queued_at = datetime.now(UTC) - timedelta(seconds=90)
    second = await create_analysis_job([1])

    expired = await get_analysis_job(first.job_id)
    active = await get_analysis_job(second.job_id)

    assert expired["status"] == "EXPIRED"
    assert second.content_ids == [1]
    assert second.skipped_inflight_ids == []
    assert active["status"] == "QUEUED"
    await reset_analysis_jobs()


@pytest.mark.asyncio
async def test_analyze_pending_sync_uses_concurrent_analysis(monkeypatch):
    called = {}

    async def fake_concurrent(content_ids, **_kwargs):
        called["ids"] = content_ids
        return [
            AiAnalysis(
                content_id=content_id,
                summary="并发分析完成",
                curation_score=60,
            )
            for content_id in content_ids
        ]

    async def fail_if_sequential_analysis_runs(*args, **kwargs):
        raise AssertionError("pending sync endpoint should use concurrent analysis")

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fake_concurrent)
    # analyze_batch_concurrent 是当前唯一的批量入口。保留同名桩以便未来
    # 端点意外回退到顺序实现时仍能立即失败，而不要求模块导出旧实现。
    monkeypatch.setattr(
        analyses_api,
        "analyze_batch",
        fail_if_sequential_analysis_runs,
        raising=False,
    )
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="最近待同步分析一",
                    url="https://example.com/sync-concurrent-1",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=2,
                    title="最近待同步分析二",
                    url="https://example.com/sync-concurrent-2",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC) - timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

        result = await analyses_api.analyze_all_pending(
            limit=10,
            hours=24,
            sync=True,
            background_tasks=BackgroundTasks(),
            db=db,
        )

    assert called["ids"] == [1, 2]
    assert result["mode"] == "sync"
    assert result["queued_ids"] == []
    assert result["analyzed_ids"] == [1, 2]
    assert result["count"] == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_endpoint_uses_concurrent_analysis(monkeypatch):
    called = {}

    async def fake_concurrent(content_ids, **_kwargs):
        called["ids"] = content_ids
        return [
            AiAnalysis(
                content_id=content_id,
                summary="批量并发分析完成",
                curation_score=60,
            )
            for content_id in content_ids
        ]

    async def fail_if_sequential_analysis_runs(*args, **kwargs):
        raise AssertionError("batch endpoint should use concurrent analysis")

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fake_concurrent)
    # 同上：兼容已移除的顺序入口，并持续防止端点回退。
    monkeypatch.setattr(
        analyses_api,
        "analyze_batch",
        fail_if_sequential_analysis_runs,
        raising=False,
    )
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        results = await analyses_api.analyze_batch_endpoint([1, 2], db=db)

    assert called["ids"] == [1, 2]
    assert [item.content_id for item in results] == [1, 2]
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_recovers_from_empty_llm_response(monkeypatch):
    async def empty_llm_response(*args, **kwargs):
        return {"raw_response": ""}

    monkeypatch.setattr(analysis, "call_llm_json", empty_llm_response)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="最近的创作者选题信号",
                url="https://example.com/recent-topic",
                source_name="测试信源",
                source_type="RSS",
                platform="rsshub",
                status=ContentStatus.PENDING,
                summary="一个关于创作者工具升级的短摘要。",
                raw_content="这是一个用于测试的内容。它需要在 LLM 返回空响应时仍然生成本地基础分析结果，避免算法流程 24 小时窗口没有评分样本。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))
        stored_content = await db.get(ContentItem, 1)

    assert [item.content_id for item in results] == [1]
    assert stored_analysis is not None
    assert stored_analysis.summary
    assert stored_analysis.curation_score and stored_analysis.curation_score > 0
    assert stored_analysis.analysis_mode == "pro_only"
    assert stored_analysis.escalated is False
    assert stored_analysis.prescreen_model is None
    assert stored_analysis.final_model == "default"
    assert stored_analysis.escalation_reason is None
    assert stored_analysis.prescreen_confidence is None
    assert stored_analysis.prescreen_score is None
    assert stored_content.status == ContentStatus.ANALYZED
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_cascade_uses_lite_result_without_pro_when_confident(monkeypatch):
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ENABLED", True)
    monkeypatch.setattr(analysis.settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_PRO_ROUTING_GROUP", "analysis_pro")
    calls = []

    async def fake_llm_json_with_metadata(messages, **kwargs):
        calls.append({"scene": kwargs.get("scene"), "routing_group": kwargs.get("routing_group")})
        if kwargs.get("scene") == "content_prescreen":
            return {
                "score": 62,
                "confidence": 0.92,
                "should_escalate": False,
                "reason": "普通观察项，暂不需要深挖",
                "tags": ["AI", "工具"],
            }, {"actual_model": "openai/lite"}
        raise AssertionError("confident lite prescreen should not call pro analysis")

    monkeypatch.setattr(analysis, "call_llm_json_with_metadata", fake_llm_json_with_metadata)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="普通工具更新",
                url="https://example.com/lite-only-analysis",
                status=ContentStatus.PENDING,
                raw_content="这是一个普通工具更新，信息量中等，适合观察但不需要深度分析。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)
        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))

    assert [item.content_id for item in results] == [1]
    assert calls == [{"scene": "content_prescreen", "routing_group": "analysis_lite"}]
    assert stored_analysis.analysis_mode == "lite_only"
    assert stored_analysis.prescreen_model == "openai/lite"
    assert stored_analysis.final_model == "openai/lite"
    assert stored_analysis.escalated is False
    assert stored_analysis.escalation_reason is None
    assert stored_analysis.prescreen_score == 62
    assert stored_analysis.prescreen_confidence == 0.92
    assert stored_analysis.curation_score == 62
    assert stored_analysis.tags == ["AI", "工具"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_cascade_escalates_high_score_to_pro(monkeypatch):
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ENABLED", True)
    monkeypatch.setattr(analysis.settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_PRO_ROUTING_GROUP", "analysis_pro")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ESCALATE_SCORE", 75.0)
    calls = []

    async def fake_llm_json_with_metadata(messages, **kwargs):
        calls.append({"scene": kwargs.get("scene"), "routing_group": kwargs.get("routing_group")})
        if kwargs.get("scene") == "content_prescreen":
            return {
                "score": 91,
                "confidence": 0.9,
                "should_escalate": False,
                "reason": "高价值内容",
                "tags": ["AI"],
            }, {"actual_model": "openai/lite"}
        if kwargs.get("scene") == "content_analysis":
            return {
                "summary": "Pro 完整分析",
                "key_points": ["重点一"],
                "recommendation": "适合深挖",
                "creator_angles": ["角度一"],
                "title_suggestions": ["标题一"],
                "risk_notes": "",
                "tags": ["AI"],
                "scores": {
                    "quality_score": 80,
                    "hot_score": 70,
                    "freshness_score": 60,
                    "creator_score": 75,
                    "viral_score": 65,
                    "risk_score": 20,
                },
                "curation": {
                    "curation_score": 82,
                    "info_density": 78,
                    "actionability": 76,
                    "source_weight": 50,
                },
            }, {"actual_model": "openai/pro"}
        raise AssertionError(f"unexpected scene: {kwargs.get('scene')}")

    monkeypatch.setattr(analysis, "call_llm_json_with_metadata", fake_llm_json_with_metadata)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="重要模型发布",
                url="https://example.com/cascade-pro-analysis",
                status=ContentStatus.PENDING,
                raw_content="一个重要模型发布，具备高传播和深挖价值。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)
        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))

    assert [item.content_id for item in results] == [1]
    assert calls == [
        {"scene": "content_prescreen", "routing_group": "analysis_lite"},
        {"scene": "content_analysis", "routing_group": "analysis_pro"},
    ]
    assert stored_analysis.analysis_mode == "cascade"
    assert stored_analysis.prescreen_model == "openai/lite"
    assert stored_analysis.final_model == "openai/pro"
    assert stored_analysis.escalated is True
    assert stored_analysis.escalation_reason == "high_prescreen_score"
    assert stored_analysis.prescreen_score == 91
    assert stored_analysis.prescreen_confidence == 0.9
    assert stored_analysis.summary == "Pro 完整分析"
    assert stored_analysis.curation_score == 82
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_cascade_escalates_low_confidence_to_pro(monkeypatch):
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ENABLED", True)
    monkeypatch.setattr(analysis.settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_PRO_ROUTING_GROUP", "analysis_pro")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_MIN_CONFIDENCE", 0.75)
    calls = []

    async def fake_llm_json_with_metadata(messages, **kwargs):
        calls.append({"scene": kwargs.get("scene"), "routing_group": kwargs.get("routing_group")})
        if kwargs.get("scene") == "content_prescreen":
            return {
                "score": 58,
                "confidence": 0.4,
                "should_escalate": False,
                "reason": "置信不足，需要深度确认",
                "tags": ["AI"],
            }, {"actual_model": "openai/lite"}
        if kwargs.get("scene") == "content_analysis":
            return {
                "summary": "低置信升级后的 Pro 分析",
                "key_points": ["重点一"],
                "recommendation": "需要深挖",
                "creator_angles": ["角度一"],
                "title_suggestions": ["标题一"],
                "risk_notes": "",
                "tags": ["AI"],
                "scores": {
                    "quality_score": 80,
                    "hot_score": 70,
                    "freshness_score": 60,
                    "creator_score": 75,
                    "viral_score": 65,
                    "risk_score": 20,
                },
                "curation": {
                    "curation_score": 79,
                    "info_density": 78,
                    "actionability": 76,
                    "source_weight": 50,
                },
            }, {"actual_model": "openai/pro"}
        raise AssertionError(f"unexpected scene: {kwargs.get('scene')}")

    monkeypatch.setattr(analysis, "call_llm_json_with_metadata", fake_llm_json_with_metadata)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="低置信预筛内容",
                url="https://example.com/cascade-low-confidence",
                status=ContentStatus.PENDING,
                raw_content="这条内容信号不稳定，Lite 预筛置信度偏低，应升级到 Pro 完整分析。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)
        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))

    assert [item.content_id for item in results] == [1]
    assert calls == [
        {"scene": "content_prescreen", "routing_group": "analysis_lite"},
        {"scene": "content_analysis", "routing_group": "analysis_pro"},
    ]
    assert stored_analysis.analysis_mode == "cascade"
    assert stored_analysis.prescreen_model == "openai/lite"
    assert stored_analysis.final_model == "openai/pro"
    assert stored_analysis.escalated is True
    assert stored_analysis.escalation_reason == "low_prescreen_confidence"
    assert stored_analysis.prescreen_score == 58
    assert stored_analysis.prescreen_confidence == 0.4
    assert stored_analysis.summary == "低置信升级后的 Pro 分析"
    assert stored_analysis.curation_score == 79
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_cascade_honors_lite_requested_escalation(monkeypatch):
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ENABLED", True)
    monkeypatch.setattr(analysis.settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_PRO_ROUTING_GROUP", "analysis_pro")
    calls = []

    async def fake_llm_json_with_metadata(messages, **kwargs):
        calls.append({"scene": kwargs.get("scene"), "routing_group": kwargs.get("routing_group")})
        if kwargs.get("scene") == "content_prescreen":
            return {
                "score": 61,
                "confidence": 0.9,
                "should_escalate": True,
                "reason": "Lite 判断需要深挖",
                "tags": ["产品"],
            }, {"actual_model": "openai/lite"}
        if kwargs.get("scene") == "content_analysis":
            return {
                "summary": "Lite 要求升级后的 Pro 分析",
                "key_points": ["重点一"],
                "recommendation": "适合深挖",
                "creator_angles": ["角度一"],
                "title_suggestions": ["标题一"],
                "risk_notes": "",
                "tags": ["产品"],
                "scores": {
                    "quality_score": 78,
                    "hot_score": 70,
                    "freshness_score": 60,
                    "creator_score": 75,
                    "viral_score": 65,
                    "risk_score": 20,
                },
                "curation": {
                    "curation_score": 81,
                    "info_density": 78,
                    "actionability": 76,
                    "source_weight": 50,
                },
            }, {"actual_model": "openai/pro"}
        raise AssertionError(f"unexpected scene: {kwargs.get('scene')}")

    monkeypatch.setattr(analysis, "call_llm_json_with_metadata", fake_llm_json_with_metadata)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="Lite 显式升级内容",
                url="https://example.com/cascade-lite-requested",
                status=ContentStatus.PENDING,
                raw_content="这条内容由 Lite 预筛显式要求升级，不能被 score 阈值覆盖。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)
        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))

    assert [item.content_id for item in results] == [1]
    assert calls == [
        {"scene": "content_prescreen", "routing_group": "analysis_lite"},
        {"scene": "content_analysis", "routing_group": "analysis_pro"},
    ]
    assert stored_analysis.analysis_mode == "cascade"
    assert stored_analysis.prescreen_model == "openai/lite"
    assert stored_analysis.final_model == "openai/pro"
    assert stored_analysis.escalated is True
    assert stored_analysis.escalation_reason == "lite_requested_escalation"
    assert stored_analysis.prescreen_score == 61
    assert stored_analysis.prescreen_confidence == 0.9
    assert stored_analysis.summary == "Lite 要求升级后的 Pro 分析"
    assert stored_analysis.curation_score == 81
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_cascade_escalates_invalid_lite_prescreen_to_pro(monkeypatch):
    monkeypatch.setattr(analysis.settings, "ANALYSIS_CASCADE_ENABLED", True)
    monkeypatch.setattr(analysis.settings, "ANALYSIS_LITE_ROUTING_GROUP", "analysis_lite")
    monkeypatch.setattr(analysis.settings, "ANALYSIS_PRO_ROUTING_GROUP", "analysis_pro")
    calls = []

    async def fake_llm_json_with_metadata(messages, **kwargs):
        calls.append({"scene": kwargs.get("scene"), "routing_group": kwargs.get("routing_group")})
        if kwargs.get("scene") == "content_prescreen":
            return {"raw_response": ""}, {"actual_model": "openai/lite"}
        if kwargs.get("scene") == "content_analysis":
            return {
                "summary": "预筛无效后的 Pro 分析",
                "key_points": ["重点一"],
                "recommendation": "需要完整分析",
                "creator_angles": ["角度一"],
                "title_suggestions": ["标题一"],
                "risk_notes": "",
                "tags": ["AI"],
                "scores": {
                    "quality_score": 76,
                    "hot_score": 70,
                    "freshness_score": 60,
                    "creator_score": 74,
                    "viral_score": 65,
                    "risk_score": 20,
                },
                "curation": {
                    "curation_score": 77,
                    "info_density": 78,
                    "actionability": 76,
                    "source_weight": 50,
                },
            }, {"actual_model": "openai/pro"}
        raise AssertionError(f"unexpected scene: {kwargs.get('scene')}")

    monkeypatch.setattr(analysis, "call_llm_json_with_metadata", fake_llm_json_with_metadata)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="预筛格式异常内容",
                url="https://example.com/cascade-invalid-prescreen",
                status=ContentStatus.PENDING,
                raw_content="Lite 返回空或格式异常时，系统应升级 Pro，不能直接用无效预筛结果落库。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)
        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))

    assert [item.content_id for item in results] == [1]
    assert calls == [
        {"scene": "content_prescreen", "routing_group": "analysis_lite"},
        {"scene": "content_analysis", "routing_group": "analysis_pro"},
    ]
    assert stored_analysis.analysis_mode == "cascade"
    assert stored_analysis.prescreen_model == "openai/lite"
    assert stored_analysis.final_model == "openai/pro"
    assert stored_analysis.escalated is True
    assert stored_analysis.escalation_reason == "prescreen_invalid"
    assert stored_analysis.prescreen_score is None
    assert stored_analysis.prescreen_confidence is None
    assert stored_analysis.summary == "预筛无效后的 Pro 分析"
    assert stored_analysis.curation_score == 77
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_normalizes_malformed_llm_contract(monkeypatch):
    async def malformed_llm_response(*args, **kwargs):
        return {
            "summary": {"bad": "object"},
            "key_points": "单点观点",
            "recommendation": 123,
            "creator_angles": ["角度", " ", "角度", {"bad": 1}],
            "title_suggestions": '["标题一", "标题二"]',
            "risk_notes": {"bad": "risk"},
            "tags": '["AI", "AI", " ", "%s", "工具"]' % ("x" * 80),
            "scores": {
                "quality_score": 120,
                "hot_score": -5,
                "freshness_score": "80",
                "creator_score": None,
                "viral_score": "bad",
                "risk_score": 90,
            },
            "curation": {
                "curation_score": 150,
                "info_density": -10,
                "actionability": "70",
                "source_weight": "bad",
            },
        }

    monkeypatch.setattr(analysis, "call_llm_json", malformed_llm_response)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="格式漂移的分析结果",
                url="https://example.com/malformed-analysis-contract",
                status=ContentStatus.PENDING,
                raw_content="用于验证 LLM 返回局部格式异常时，分析结果仍会以稳定契约落库。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))
        stored_content = await db.get(ContentItem, 1)

    assert [item.content_id for item in results] == [1]
    assert stored_content.status == ContentStatus.ANALYZED
    assert stored_analysis.quality_score == 100
    assert stored_analysis.hot_score == 0
    assert stored_analysis.freshness_score == 80
    assert stored_analysis.creator_score == 50
    assert stored_analysis.viral_score == 50
    assert stored_analysis.risk_score == 90
    assert stored_analysis.curation_score == 100
    assert stored_analysis.info_density == 0
    assert stored_analysis.actionability == 70
    assert stored_analysis.source_weight == 50
    assert stored_analysis.summary == ""
    assert stored_analysis.key_points == ["单点观点"]
    assert stored_analysis.creator_angles == ["角度"]
    assert stored_analysis.title_suggestions == ["标题一", "标题二"]
    assert stored_analysis.recommendation == ""
    assert stored_analysis.risk_notes == {"notes": ""}
    assert stored_analysis.tags == ["AI", "x" * 40, "工具"]
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_retries_stale_analyzing_content(monkeypatch):
    async def empty_llm_response(*args, **kwargs):
        return {"raw_response": ""}

    monkeypatch.setattr(analysis, "call_llm_json", empty_llm_response)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="超时分析任务",
                url="https://example.com/stale-analysis-task",
                source_name="测试信源",
                source_type="RSS",
                platform="rsshub",
                status=ContentStatus.ANALYZING,
                updated_at=datetime.now(UTC) - timedelta(minutes=ANALYSIS_STALE_MINUTES + 5),
                raw_content="这是一条分析中状态超时的内容，应当重新进入算法分析流程。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))
        stored_content = await db.get(ContentItem, 1)

    assert [item.content_id for item in results] == [1]
    assert stored_analysis is not None
    assert stored_content.status == ContentStatus.ANALYZED
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_retries_stale_error_content(monkeypatch):
    async def empty_llm_response(*args, **kwargs):
        return {"raw_response": ""}

    monkeypatch.setattr(analysis, "call_llm_json", empty_llm_response)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="失败后可恢复内容",
                url="https://example.com/stale-error-analysis-task",
                source_name="测试信源",
                source_type="RSS",
                platform="rsshub",
                status=ContentStatus.ERROR,
                updated_at=datetime.now(UTC) - timedelta(minutes=ANALYSIS_STALE_MINUTES + 5),
                raw_content="这是一条之前分析失败的内容，冷却后应当重新进入算法分析流程。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_analysis = await db.scalar(select(AiAnalysis).where(AiAnalysis.content_id == 1))
        stored_content = await db.get(ContentItem, 1)

    assert [item.content_id for item in results] == [1]
    assert stored_analysis is not None
    assert stored_content.status == ContentStatus.ANALYZED
    await engine.dispose()


@pytest.mark.asyncio
async def test_analysis_failure_sets_error_cooldown_timestamp(monkeypatch):
    async def failing_llm(*args, **kwargs):
        raise RuntimeError("temporary provider failure")

    monkeypatch.setattr(analysis, "call_llm_json", failing_llm)
    engine, session_factory = await _session_factory()
    old_timestamp = datetime.now(UTC) - timedelta(days=1)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="临时失败内容",
                url="https://example.com/temporary-provider-failure",
                status=ContentStatus.PENDING,
                updated_at=old_timestamp,
                raw_content="用于验证失败后不会被立即忙等重试。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_content = await db.get(ContentItem, 1)

    assert results == []
    assert stored_content.status == ContentStatus.ERROR
    assert stored_content.updated_at > old_timestamp
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_skips_fresh_analyzing_content(monkeypatch):
    async def fail_if_llm_runs(*args, **kwargs):
        raise AssertionError("fresh analyzing content should not be retried")

    monkeypatch.setattr(analysis, "call_llm_json", fail_if_llm_runs)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="刚开始分析任务",
                url="https://example.com/fresh-analysis-task",
                status=ContentStatus.ANALYZING,
                updated_at=datetime.now(UTC),
                raw_content="这是一条刚进入分析中的内容，不应被重复抢占。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_content = await db.get(ContentItem, 1)

    assert results == []
    assert stored_content.status == ContentStatus.ANALYZING
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_commits_analyzing_status_before_llm_call(monkeypatch):
    engine, session_factory = await _session_factory()
    observed = {}

    async def fake_analyze_content(content, db):
        async with session_factory() as observer:
            stored_content = await observer.get(ContentItem, content.id)
            observed["status_before_analysis"] = stored_content.status

        analysis_record = AiAnalysis(
            content_id=content.id,
            summary="已分析",
            curation_score=60,
            quality_score=60,
            hot_score=60,
            freshness_score=60,
            creator_score=60,
            viral_score=60,
            risk_score=20,
        )
        db.add(analysis_record)
        content.status = ContentStatus.ANALYZED
        await db.flush()
        return analysis_record

    monkeypatch.setattr(analysis, "analyze_content", fake_analyze_content)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="事务边界测试内容",
                url="https://example.com/analysis-transaction",
                status=ContentStatus.PENDING,
                raw_content="用于验证批量分析不会把外部 LLM 调用包在长写事务中。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_content = await db.get(ContentItem, 1)

    assert observed["status_before_analysis"] == ContentStatus.ANALYZING
    assert [item.content_id for item in results] == [1]
    assert stored_content.status == ContentStatus.ANALYZED
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_invalidates_scoring_cache_after_commit(monkeypatch):
    engine, session_factory = await _session_factory()
    invalidate_scoring_flow_cache()
    _cache_and_return(
        24, 160, 80, None,
        build_empty_payload(
            hours=24,
            analyzed_total=0,
            window_total=0,
            ignored_count=0,
            limit=160,
            sample_limit=80,
        ),
    )
    observed = {}

    async def fake_analyze_content(content, db):
        analysis_record = AiAnalysis(
            content_id=content.id,
            summary="已分析",
            curation_score=60,
            quality_score=60,
            hot_score=60,
            freshness_score=60,
            creator_score=60,
            viral_score=60,
            risk_score=20,
        )
        db.add(analysis_record)
        content.status = ContentStatus.ANALYZED
        await db.flush()
        observed["cache_before_commit"] = get_cached_scoring_flow_json(hours=24, limit=160) is not None
        return analysis_record

    monkeypatch.setattr(analysis, "analyze_content", fake_analyze_content)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="缓存提交边界测试内容",
                url="https://example.com/analysis-cache-boundary",
                status=ContentStatus.PENDING,
                raw_content="用于验证分析完成后只在提交成功之后刷新算法缓存。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

    assert observed["cache_before_commit"] is True
    assert [item.content_id for item in results] == [1]
    assert get_cached_scoring_flow_json(hours=24, limit=160) is None

    invalidate_scoring_flow_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_single_commits_analyzing_status_before_llm_call(monkeypatch):
    engine, session_factory = await _session_factory()
    observed = {}

    async def fake_analyze_content(content, db):
        async with session_factory() as observer:
            stored_content = await observer.get(ContentItem, content.id)
            observed["status_before_analysis"] = stored_content.status

        analysis_record = AiAnalysis(
            content_id=content.id,
            summary="已分析",
            curation_score=60,
            quality_score=60,
            hot_score=60,
            freshness_score=60,
            creator_score=60,
            viral_score=60,
            risk_score=20,
        )
        db.add(analysis_record)
        content.status = ContentStatus.ANALYZED
        await db.flush()
        return analysis_record

    monkeypatch.setattr(analyses_api, "analyze_content", fake_analyze_content)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="单条事务边界测试内容",
                url="https://example.com/single-analysis-transaction",
                status=ContentStatus.PENDING,
                raw_content="用于验证单条分析接口不会把外部 LLM 调用包在长写事务中。",
            )
        )
        await db.commit()

        result = await analyses_api.analyze_single(1, db=db)

        stored_content = await db.get(ContentItem, 1)

    assert observed["status_before_analysis"] == ContentStatus.ANALYZING
    assert result.content_id == 1
    assert stored_content.status == ContentStatus.ANALYZED
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_single_rejects_fresh_analyzing_claim(monkeypatch):
    engine, session_factory = await _session_factory()

    async def fail_analyze_content(content, db):
        raise AssertionError("fresh analyzing content should not start another LLM call")

    monkeypatch.setattr(analyses_api, "analyze_content", fail_analyze_content)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="正在分析的单条内容",
                url="https://example.com/single-fresh-analyzing",
                status=ContentStatus.ANALYZING,
                updated_at=datetime.now(UTC),
                raw_content="用于验证单条分析接口不会绕过分析租约重复启动。",
            )
        )
        await db.commit()

        with pytest.raises(Exception) as exc_info:
            await analyses_api.analyze_single(1, db=db)

        stored_content = await db.get(ContentItem, 1)

    assert getattr(exc_info.value, "status_code", None) == 409
    assert str(exc_info.value.detail) == "Content is already being analyzed"
    assert stored_content.status == ContentStatus.ANALYZING
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_single_invalidates_scoring_cache_after_commit(monkeypatch):
    engine, session_factory = await _session_factory()
    invalidate_scoring_flow_cache()
    _cache_and_return(
        24, 160, 80, None,
        build_empty_payload(
            hours=24,
            analyzed_total=0,
            window_total=0,
            ignored_count=0,
            limit=160,
            sample_limit=80,
        ),
    )
    observed = {}

    async def fake_analyze_content(content, db):
        analysis_record = AiAnalysis(
            content_id=content.id,
            summary="单条已分析",
            curation_score=60,
            quality_score=60,
            hot_score=60,
            freshness_score=60,
            creator_score=60,
            viral_score=60,
            risk_score=20,
        )
        db.add(analysis_record)
        content.status = ContentStatus.ANALYZED
        await db.flush()
        observed["cache_before_commit"] = get_cached_scoring_flow_json(hours=24, limit=160) is not None
        return analysis_record

    monkeypatch.setattr(analyses_api, "analyze_content", fake_analyze_content)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="单条缓存提交边界测试内容",
                url="https://example.com/single-analysis-cache-boundary",
                status=ContentStatus.PENDING,
                raw_content="用于验证单条分析接口只在提交成功之后刷新算法缓存。",
            )
        )
        await db.commit()

        result = await analyses_api.analyze_single(1, db=db)

    assert observed["cache_before_commit"] is True
    assert result.content_id == 1
    assert get_cached_scoring_flow_json(hours=24, limit=160) is None

    invalidate_scoring_flow_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_single_failure_sets_error_cooldown_timestamp(monkeypatch):
    async def failing_analyze_content(content, db):
        raise RuntimeError("temporary single analysis failure")

    monkeypatch.setattr(analyses_api, "analyze_content", failing_analyze_content)
    engine, session_factory = await _session_factory()
    old_timestamp = datetime.now(UTC) - timedelta(days=1)

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="单条临时失败内容",
                url="https://example.com/single-temporary-failure",
                status=ContentStatus.PENDING,
                updated_at=old_timestamp,
                raw_content="用于验证单条分析接口失败后不会被后台队列立即忙等重试。",
            )
        )
        await db.commit()

        with pytest.raises(HTTPException):
            await analyses_api.analyze_single(1, db=db)

        stored_content = await db.get(ContentItem, 1)

    assert stored_content.status == ContentStatus.ERROR
    assert stored_content.updated_at > old_timestamp
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_skips_sqlite_locked_item_without_crashing(monkeypatch):
    async def locked_write(*args, **kwargs):
        raise OperationalError("UPDATE content_items", {}, Exception("database is locked"))

    monkeypatch.setattr(analysis, "retry_sqlite_locked", locked_write)
    engine, session_factory = await _session_factory()

    async with session_factory() as db:
        db.add(
            ContentItem(
                id=1,
                title="数据库锁测试内容",
                url="https://example.com/sqlite-locked",
                status=ContentStatus.PENDING,
                raw_content="用于验证 SQLite 锁定时分析批处理不会因为回滚后的 ORM 属性访问而崩溃。",
            )
        )
        await db.commit()

        results = await analysis.analyze_batch([1], db)

        stored_content = await db.get(ContentItem, 1)

    assert results == []
    assert stored_content.status == ContentStatus.PENDING
    await engine.dispose()


@pytest.mark.asyncio
async def test_analyze_batch_concurrent_runs_items_in_parallel(monkeypatch):
    engine, session_factory = await _session_factory()
    active = 0
    max_active = 0
    lock = asyncio.Lock()

    async def fake_analyze_content(content, db):
        nonlocal active, max_active
        async with lock:
            active += 1
            max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        async with lock:
            active -= 1

        analysis_record = AiAnalysis(
            content_id=content.id,
            summary="已分析",
            curation_score=60,
            quality_score=60,
            hot_score=60,
            freshness_score=60,
            creator_score=60,
            viral_score=60,
            risk_score=20,
        )
        db.add(analysis_record)
        content.status = ContentStatus.ANALYZED
        await db.flush()
        return analysis_record

    monkeypatch.setattr(analysis, "analyze_content", fake_analyze_content)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=item_id,
                    title=f"并发分析内容 {item_id}",
                    url=f"https://example.com/concurrent-{item_id}",
                    status=ContentStatus.PENDING,
                    raw_content="用于验证并发分析 worker 不共享 session，且 LLM 调用可以重叠执行。",
                )
                for item_id in range(1, 5)
            ]
        )
        await db.commit()

    results = await analysis.analyze_batch_concurrent(
        [1, 2, 3, 4],
        concurrency=2,
        session_factory=session_factory,
    )

    async with session_factory() as db:
        statuses = {item.id: item.status for item in (await db.execute(select(ContentItem))).scalars().all()}

    assert [item.content_id for item in results] == [1, 2, 3, 4]
    assert max_active == 2
    assert statuses == {
        1: ContentStatus.ANALYZED,
        2: ContentStatus.ANALYZED,
        3: ContentStatus.ANALYZED,
        4: ContentStatus.ANALYZED,
    }
    await engine.dispose()


def test_source_sync_semaphore_uses_configured_concurrency(monkeypatch):
    scheduler_module._sync_semaphore = None
    scheduler_module._sync_semaphore_limit = None
    monkeypatch.setattr(scheduler_module.settings, "SOURCE_SYNC_WORKER_CONCURRENCY", 7)

    first = scheduler_module._get_semaphore()

    assert scheduler_module._sync_semaphore_limit == 7
    assert first._value == 7

    monkeypatch.setattr(scheduler_module.settings, "SOURCE_SYNC_WORKER_CONCURRENCY", 2)
    second = scheduler_module._get_semaphore()

    assert scheduler_module._sync_semaphore_limit == 2
    assert second._value == 2
    assert second is not first

    scheduler_module._sync_semaphore = None
    scheduler_module._sync_semaphore_limit = None


@pytest.mark.asyncio
async def test_post_sync_drain_processes_backlog_and_stale_analyzing(monkeypatch):
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)

    monkeypatch.setattr(scheduler_module, "async_session", session_factory)

    async def fake_analyze_batch(content_ids, **_kwargs):
        results = []
        async with session_factory() as db:
            for content_id in content_ids:
                content = await db.get(ContentItem, content_id)
                if content is None:
                    continue
                analysis_record = AiAnalysis(
                    content_id=content.id,
                    summary="已分析",
                    curation_score=60,
                    quality_score=60,
                    hot_score=60,
                    freshness_score=60,
                    creator_score=60,
                    viral_score=60,
                    risk_score=20,
                )
                db.add(analysis_record)
                content.status = ContentStatus.ANALYZED
                await db.flush()
                results.append(analysis_record)
            await db.commit()
        return results

    monkeypatch.setattr(scheduler_module, "analyze_batch_concurrent", fake_analyze_batch)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="最新待分析一",
                    url="https://example.com/pending-1",
                    status=ContentStatus.PENDING,
                    crawled_at=now,
                ),
                ContentItem(
                    id=2,
                    title="最新待分析二",
                    url="https://example.com/pending-2",
                    status=ContentStatus.PENDING,
                    crawled_at=now - timedelta(minutes=1),
                ),
                ContentItem(
                    id=3,
                    title="超时分析中内容",
                    url="https://example.com/stale-analyzing",
                    status=ContentStatus.ANALYZING,
                    crawled_at=now - timedelta(minutes=2),
                    updated_at=now - timedelta(minutes=ANALYSIS_STALE_MINUTES + 1),
                ),
            ]
        )
        await db.commit()

    stats = await scheduler_module._drain_pending_analysis(
        batch_size=2,
        time_budget_seconds=120,
    )

    async with session_factory() as db:
        statuses = {item.id: item.status for item in (await db.execute(select(ContentItem))).scalars().all()}

    assert stats == {
        "attempted": 3,
        "analyzed": 3,
        "batches": 2,
        "remaining": False,
        "stop_reason": "no_pending",
    }
    assert statuses == {
        1: ContentStatus.ANALYZED,
        2: ContentStatus.ANALYZED,
        3: ContentStatus.ANALYZED,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_post_sync_drain_uses_configured_default_batch_size(monkeypatch):
    engine, session_factory = await _session_factory()
    now = datetime.now(UTC)
    calls = []

    monkeypatch.setattr(scheduler_module, "async_session", session_factory)
    monkeypatch.setattr(scheduler_module.settings, "POST_SYNC_ANALYSIS_BATCH_SIZE", 3)
    monkeypatch.setattr(scheduler_module.settings, "POST_SYNC_ANALYSIS_TIME_BUDGET_SECONDS", 120)
    monkeypatch.setattr(scheduler_module.settings, "POST_SYNC_MIN_REMAINING_SECONDS", 1)

    async def fake_analyze_batch(content_ids, **_kwargs):
        calls.append(list(content_ids))
        results = []
        async with session_factory() as db:
            for content_id in content_ids:
                content = await db.get(ContentItem, content_id)
                if content is None:
                    continue
                analysis_record = AiAnalysis(
                    content_id=content.id,
                    summary="按配置批量分析",
                    curation_score=60,
                )
                db.add(analysis_record)
                content.status = ContentStatus.ANALYZED
                await db.flush()
                results.append(analysis_record)
            await db.commit()
        return results

    monkeypatch.setattr(scheduler_module, "analyze_batch_concurrent", fake_analyze_batch)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=content_id,
                    title=f"配置批量 {content_id}",
                    url=f"https://example.com/configured-batch-{content_id}",
                    status=ContentStatus.PENDING,
                    crawled_at=now - timedelta(minutes=content_id),
                )
                for content_id in range(1, 5)
            ]
        )
        await db.commit()

    stats = await scheduler_module._drain_pending_analysis()

    assert calls == [[1, 2, 3], [4]]
    assert stats == {
        "attempted": 4,
        "analyzed": 4,
        "batches": 2,
        "remaining": False,
        "stop_reason": "no_pending",
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_post_sync_drain_releases_claims_after_batch_timeout(monkeypatch):
    engine, session_factory = await _session_factory()
    monkeypatch.setattr(scheduler_module, "async_session", session_factory)

    async def fake_analyze_batch(content_ids, **_kwargs):
        async with session_factory() as db:
            for content_id in content_ids:
                content = await db.get(ContentItem, content_id)
                if content is not None:
                    content.status = ContentStatus.ANALYZING
            await db.commit()
        raise TimeoutError()

    monkeypatch.setattr(scheduler_module, "analyze_batch_concurrent", fake_analyze_batch)

    async with session_factory() as db:
        db.add_all(
            [
                ContentItem(
                    id=1,
                    title="超时释放一",
                    url="https://example.com/timeout-release-1",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC),
                ),
                ContentItem(
                    id=2,
                    title="超时释放二",
                    url="https://example.com/timeout-release-2",
                    status=ContentStatus.PENDING,
                    crawled_at=datetime.now(UTC) - timedelta(minutes=1),
                ),
            ]
        )
        await db.commit()

    stats = await scheduler_module._drain_pending_analysis(
        batch_size=2,
        time_budget_seconds=120,
    )

    async with session_factory() as db:
        statuses = {item.id: item.status for item in (await db.execute(select(ContentItem))).scalars().all()}

    assert stats == {
        "attempted": 2,
        "analyzed": 0,
        "batches": 1,
        "remaining": True,
        "stop_reason": "batch_timeout",
    }
    assert statuses == {
        1: ContentStatus.PENDING,
        2: ContentStatus.PENDING,
    }
    await engine.dispose()


@pytest.mark.asyncio
async def test_post_sync_pipeline_request_only_when_new_content(monkeypatch):
    created = []

    async def fake_pipeline():
        await asyncio.Event().wait()

    class FakeLoop:
        def create_task(self, coroutine):
            task = asyncio.create_task(coroutine)
            created.append(task)
            return task

    post_sync_pipeline_module._post_sync_task = None
    post_sync_pipeline_module._post_sync_rerun_requested = False
    monkeypatch.setattr(scheduler_module, "_run_post_sync_pipeline", fake_pipeline)
    monkeypatch.setattr(scheduler_module.asyncio, "get_running_loop", lambda: FakeLoop())

    assert scheduler_module._request_post_sync_pipeline({"new": 0}) is False
    assert scheduler_module._request_post_sync_pipeline({"new": "bad"}) is False
    assert scheduler_module._request_post_sync_pipeline({"new": 2}) is True
    assert scheduler_module._request_post_sync_pipeline({"new": 3}) is True
    assert len(created) == 1
    assert post_sync_pipeline_module._post_sync_rerun_requested is True

    created[0].cancel()
    await asyncio.gather(created[0], return_exceptions=True)
    post_sync_pipeline_module._post_sync_task = None
    post_sync_pipeline_module._post_sync_rerun_requested = False


@pytest.mark.asyncio
async def test_post_sync_pipeline_task_reference_clears_when_done(monkeypatch):
    async def fake_pipeline():
        return None

    class FakeLoop:
        def create_task(self, coroutine):
            return asyncio.create_task(coroutine)

    post_sync_pipeline_module._post_sync_task = None
    post_sync_pipeline_module._post_sync_rerun_requested = False
    monkeypatch.setattr(scheduler_module, "_run_post_sync_pipeline", fake_pipeline)
    monkeypatch.setattr(scheduler_module.asyncio, "get_running_loop", lambda: FakeLoop())

    assert scheduler_module._request_post_sync_pipeline({"new": 1}) is True
    assert post_sync_pipeline_module._post_sync_task is not None
    await post_sync_pipeline_module._post_sync_task
    await asyncio.sleep(0)

    assert post_sync_pipeline_module._post_sync_task is None


@pytest.mark.asyncio
async def test_sync_single_source_requests_post_sync_pipeline_for_new_content(monkeypatch):
    engine, session_factory = await _session_factory()
    requested = []

    monkeypatch.setattr(scheduler_module, "async_session", session_factory)

    async def fake_ingest_from_source(source, db):
        return {"fetched": 3, "new": 2, "duplicates": 1}

    def fake_request_post_sync_pipeline(stats):
        requested.append(stats)
        return True

    monkeypatch.setattr(scheduler_module, "ingest_from_source", fake_ingest_from_source)
    monkeypatch.setattr(scheduler_module, "_request_post_sync_pipeline", fake_request_post_sync_pipeline)

    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="测试信源",
                source_type="RSS",
                url="https://example.com/rss.xml",
                enabled=True,
            )
        )
        await db.commit()

    await scheduler_module._sync_single_source(1)

    assert requested == [{"fetched": 3, "new": 2, "duplicates": 1}]
    await engine.dispose()


@pytest.mark.asyncio
async def test_sync_single_source_skips_active_sync_lease(monkeypatch):
    engine, session_factory = await _session_factory()
    requested = []

    monkeypatch.setattr(scheduler_module, "async_session", session_factory)

    async def fail_ingest_from_source(source, db):
        raise AssertionError("active sync lease should skip scheduler ingest")

    def fake_request_post_sync_pipeline(stats):
        requested.append(stats)
        return True

    monkeypatch.setattr(scheduler_module, "ingest_from_source", fail_ingest_from_source)
    monkeypatch.setattr(scheduler_module, "_request_post_sync_pipeline", fake_request_post_sync_pipeline)

    async with session_factory() as db:
        db.add(
            Source(
                id=1,
                name="忙碌信源",
                source_type="RSS",
                url="https://example.com/busy.xml",
                enabled=True,
                status="syncing",
                last_sync_at=datetime.now(UTC),
            )
        )
        await db.commit()

    await scheduler_module._sync_single_source(1)

    assert requested == []
    await engine.dispose()
