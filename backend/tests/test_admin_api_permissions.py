from __future__ import annotations

from collections.abc import AsyncGenerator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import (
    analyses as analyses_api,
    auth as auth_api,
    fanqie as fanqie_api,
    llm_models as llm_models_api,
    qimao as qimao_api,
    scheduler as scheduler_api,
    settings as settings_api,
    sources as sources_api,
    topics as topics_api,
    webnovel_reports as webnovel_reports_api,
    zhihu as zhihu_api,
)
from app.core.database import Base
from app.models.topic import TopicGroup
from app.services import duckdb_service
from app.services.auth_service import create_session, create_user
from app.services.llm.model_list_cache import invalidate_model_list_cache
from app.services.source_cache import invalidate_source_list_cache


@pytest_asyncio.fixture
async def admin_api_client(monkeypatch) -> AsyncGenerator[tuple[httpx.AsyncClient, str, str], None]:
    invalidate_model_list_cache()
    invalidate_source_list_cache()

    class FakeAnalytics:
        def status(self):
            return {
                "status": "ok",
                "available": True,
                "backend": "postgresql",
                "extension": "postgres",
                "attach_alias": "oltp_db",
                "mode": "duckdb_attach_read_only",
                "error": None,
            }

    monkeypatch.setattr(duckdb_service, "get_analytics", lambda: FakeAnalytics())

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        db.add(TopicGroup(name="公开话题", keywords=["topic"], content_count=0, best_score=12.0))
        await db.commit()

    app = FastAPI()
    app.include_router(auth_api.router)
    app.include_router(sources_api.router)
    app.include_router(settings_api.router)
    app.include_router(fanqie_api.router)
    app.include_router(qimao_api.router)
    app.include_router(zhihu_api.router)
    app.include_router(webnovel_reports_api.router)
    app.include_router(llm_models_api.router)
    app.include_router(scheduler_api.router)
    app.include_router(topics_api.router)
    app.include_router(analyses_api.router)

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    for dependency in {
        auth_api.get_db,
        sources_api.get_db,
        settings_api.get_db,
        fanqie_api.get_db,
        qimao_api.get_db,
        zhihu_api.get_db,
        webnovel_reports_api.get_db,
        llm_models_api.get_db,
        topics_api.get_db,
        analyses_api.get_db,
    }:
        app.dependency_overrides[dependency] = override_get_db

    async def fake_jobs():
        return []

    monkeypatch.setattr(scheduler_api, "get_all_job_configs", fake_jobs)

    async def fake_cluster_topics_with_lease(db, *, trigger_type: str = "manual"):
        return {"groups": 1}, True

    monkeypatch.setattr(topics_api, "cluster_topics_with_lease", fake_cluster_topics_with_lease)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client, user_token, admin_token

    invalidate_model_list_cache()
    invalidate_source_list_cache()
    await engine.dispose()


@pytest.mark.asyncio
async def test_management_apis_require_admin_role(admin_api_client):
    client, user_token, admin_token = admin_api_client
    # 注意: GET /sources 已改为公开读 API (无 Depends), 不再属于管理接口
    endpoints = [
        "/settings/duckdb/status",
        "/models",
        "/scheduler/jobs",
    ]

    for endpoint in endpoints:
        anonymous = await client.get(endpoint)
        assert anonymous.status_code == 401, endpoint

        ordinary = await client.get(endpoint, headers={"Authorization": f"Bearer {user_token}"})
        assert ordinary.status_code == 403, endpoint

        admin = await client.get(endpoint, headers={"Authorization": f"Bearer {admin_token}"})
        assert admin.status_code == 200, endpoint


@pytest.mark.asyncio
async def test_webnovel_read_apis_require_login_not_admin(admin_api_client):
    client, user_token, admin_token = admin_api_client
    endpoints = [
        "/fanqie/categories",
        "/fanqie/rankings",
        "/fanqie/category/1/books",
        "/qimao/rankings",
        "/qimao/categories",
        "/qimao/books",
        "/zhihu/categories",
        "/zhihu/albums",
        "/webnovel/reports/weekly?days=7",
    ]

    for endpoint in endpoints:
        anonymous = await client.get(endpoint)
        assert anonymous.status_code == 401, endpoint

        ordinary = await client.get(endpoint, headers={"Authorization": f"Bearer {user_token}"})
        assert ordinary.status_code == 200, endpoint

        admin = await client.get(endpoint, headers={"Authorization": f"Bearer {admin_token}"})
        assert admin.status_code == 200, endpoint


@pytest.mark.asyncio
async def test_webnovel_sync_apis_still_require_admin(admin_api_client, monkeypatch):
    client, user_token, admin_token = admin_api_client
    sync_calls = []

    async def fake_fanqie_sync():
        sync_calls.append("fanqie")
        return {"status": "ok"}

    async def fake_qimao_sync():
        sync_calls.append("qimao")

    async def fake_zhihu_sync():
        sync_calls.append("zhihu")

    # endpoint 通过 BackgroundTasks 调度 app.scheduler._sync_fanqie / _sync_qimao / _sync_zhihu
    # （endpoint 内部 from app.scheduler import _sync_fanqie 局部 import）。
    # 因此 monkeypatch 目标必须是 scheduler 模块的函数对象，而不是 service 层的 full_sync 等。
    from app import scheduler as scheduler_module

    monkeypatch.setattr(scheduler_module, "_sync_fanqie", fake_fanqie_sync)
    monkeypatch.setattr(scheduler_module, "_sync_qimao", fake_qimao_sync)
    monkeypatch.setattr(scheduler_module, "_sync_zhihu", fake_zhihu_sync)

    endpoints = [
        "/fanqie/sync",
        "/qimao/sync",
        "/zhihu/sync",
    ]

    for endpoint in endpoints:
        anonymous = await client.post(endpoint)
        assert anonymous.status_code == 401, endpoint

        ordinary = await client.post(endpoint, headers={"Authorization": f"Bearer {user_token}"})
        assert ordinary.status_code == 403, endpoint

        admin = await client.post(endpoint, headers={"Authorization": f"Bearer {admin_token}"})
        assert admin.status_code == 200, endpoint
        # ASGITransport 下 background task 在 response 返回后由事件循环调度，
        # 需要 await asyncio.sleep(0) 让出控制权让 fake sync 函数执行。
        import asyncio

        await asyncio.sleep(0)

    assert sync_calls == ["fanqie", "qimao", "zhihu"]


@pytest.mark.asyncio
async def test_webnovel_sync_jobs_skip_when_lease_is_active(monkeypatch):
    from app import scheduler as scheduler_module
    from app.services import fanqie_service, job_tracker, qimao_service, zhihu_service

    skipped_jobs = []

    async def fake_claim_job_run(job_key: str, name: str, description: str, timeout: int):
        return False

    async def fake_record_skipped_job(job_key: str, trigger_type: str, summary: str):
        skipped_jobs.append(job_key)

    async def fail_qimao_sync():
        raise AssertionError("qimao sync should be skipped while a lease is active")

    async def fail_zhihu_sync():
        raise AssertionError("zhihu sync should be skipped while a lease is active")

    async def fail_fanqie_sync():
        raise AssertionError("fanqie sync should be skipped while a lease is active")

    monkeypatch.setattr(job_tracker, "_claim_job_run", fake_claim_job_run)
    monkeypatch.setattr(job_tracker, "_record_skipped_job", fake_record_skipped_job)
    monkeypatch.setattr(fanqie_service, "full_sync", fail_fanqie_sync)
    monkeypatch.setattr(qimao_service, "sync_qimao_ranks", fail_qimao_sync)
    monkeypatch.setattr(zhihu_service, "sync_zhihu_ranks", fail_zhihu_sync)

    await scheduler_module._sync_fanqie()
    await scheduler_module._sync_qimao()
    await scheduler_module._sync_zhihu()

    assert skipped_jobs == ["sync_fanqie", "sync_qimao", "sync_zhihu"]


@pytest.mark.asyncio
async def test_topic_reads_are_public_but_clustering_requires_admin(admin_api_client):
    client, user_token, admin_token = admin_api_client

    public_list = await client.get("/topics")
    assert public_list.status_code == 200
    assert public_list.json()["items"][0]["name"] == "公开话题"

    anonymous = await client.post("/topics/cluster")
    assert anonymous.status_code == 401

    ordinary = await client.post("/topics/cluster", headers={"Authorization": f"Bearer {user_token}"})
    assert ordinary.status_code == 403

    admin = await client.post("/topics/cluster", headers={"Authorization": f"Bearer {admin_token}"})
    assert admin.status_code == 200
    assert admin.json() == {"status": "ok", "stats": {"groups": 1}}


@pytest.mark.asyncio
async def test_topic_clustering_returns_conflict_when_lease_is_active(admin_api_client, monkeypatch):
    client, _user_token, admin_token = admin_api_client

    async def fake_skipped_cluster(db, *, trigger_type: str = "manual"):
        return None, False

    monkeypatch.setattr(topics_api, "cluster_topics_with_lease", fake_skipped_cluster)

    response = await client.post("/topics/cluster", headers={"Authorization": f"Bearer {admin_token}"})

    assert response.status_code == 409
    assert "正在运行" in response.json()["detail"]


@pytest.mark.asyncio
async def test_batch_analysis_requires_admin(admin_api_client, monkeypatch):
    """Batch and pending analysis endpoints must require admin role.

    These endpoints trigger LLM calls for multiple content items — allowing
    any authenticated user to invoke them would enable cost abuse.
    """
    client, user_token, admin_token = admin_api_client

    # Stub out the actual analysis work so the test doesn't call LLM APIs
    async def fake_analyze_batch(content_ids, assume_claimed=False):
        return []

    async def fake_claim_pending(db, *, limit, hours):
        return []

    monkeypatch.setattr(analyses_api, "analyze_batch_concurrent", fake_analyze_batch)
    monkeypatch.setattr(
        "app.repositories.content_repo.ContentRepo.claim_pending_analysis_ids",
        fake_claim_pending,
    )

    # /analyses/batch — anonymous → 401, user → 403, admin → 200
    batch_url = "/analyses/batch"

    anonymous = await client.post(batch_url, json=[1, 2])
    assert anonymous.status_code == 401

    ordinary = await client.post(batch_url, json=[1, 2], headers={"Authorization": f"Bearer {user_token}"})
    assert ordinary.status_code == 403

    admin = await client.post(batch_url, json=[1, 2], headers={"Authorization": f"Bearer {admin_token}"})
    assert admin.status_code == 200

    # /analyses/pending — anonymous → 401, user → 403, admin → 200
    pending_url = "/analyses/pending"

    anonymous_pending = await client.post(pending_url)
    assert anonymous_pending.status_code == 401

    ordinary_pending = await client.post(pending_url, headers={"Authorization": f"Bearer {user_token}"})
    assert ordinary_pending.status_code == 403

    admin_pending = await client.post(pending_url, headers={"Authorization": f"Bearer {admin_token}"})
    assert admin_pending.status_code == 200
