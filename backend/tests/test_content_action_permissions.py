from __future__ import annotations

from typing import AsyncGenerator

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.main  # noqa: F401 - import all models for Base.metadata
from app.api.v1 import auth as auth_api
from app.api.v1 import contents as contents_api
from app.core.database import Base
from datetime import datetime, timezone
from app.models.content import ContentItem, ContentStatus
from app.models.source import Source, SourceType, SourceStatus
from app.models.user import User
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.repositories.analysis_repo import AnalysisRepository
from app.services import enricher
from app.services.auth_service import create_session, create_user


@pytest.mark.asyncio
async def test_content_read_strips_raw_content_and_management_requires_admin(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="content-user@example.com", password="Password123", role="user")
        admin = await create_user(db, email="content-admin@example.com", password="Password123", role="admin")
        user_token, _ = await create_session(db, user)
        admin_token, _ = await create_session(db, admin)
        db.add(
            ContentItem(
                id=1,
                title="内容动作权限样本",
                url="https://example.com/content-actions",
                source_name="测试信源",
                source_type="RSS",
                raw_content="只有管理员应该看到的原文",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add(
            ContentItem(
                id=2,
                title="批量增强权限样本",
                url="https://example.com/content-actions-batch",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add(
            AiAnalysis(
                content_id=1,
                summary="测试摘要",
                curation_score=88,
                enrichment_status="pending",
            )
        )
        db.add(
            AiAnalysis(
                content_id=2,
                summary="批量摘要",
                curation_score=92,
                info_density=90,
                actionability=90,
                source_weight=70,
                creator_score=90,
                viral_score=80,
                freshness_score=90,
                quality_score=90,
                hot_score=80,
                risk_score=0,
                enrichment_status="pending",
            )
        )
        await db.commit()

    async def fake_enrich_content(content_id: int, db: AsyncSession):
        return {
            "background_knowledge": "背景",
            "why_matters": "重要",
            "related_angles": [],
            "creator_tips": [],
            "story_hooks": [],
        }

    async def fake_enrich_batch(content_ids: list[int], db: AsyncSession):
        return [{"content_id": content_id, "status": "completed"} for content_id in content_ids]

    monkeypatch.setattr(enricher, "enrich_content", fake_enrich_content)
    monkeypatch.setattr(enricher, "enrich_batch", fake_enrich_batch)

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
    app.dependency_overrides[contents_api.get_db] = override_get_db
    monkeypatch.setattr(contents_api, "async_session", session_factory)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        public_detail = await client.get("/contents/1")
        assert public_detail.status_code == 200
        assert public_detail.json()["title"] == "内容动作权限样本"
        assert public_detail.json()["raw_content"] is None

        public_list = await client.get("/contents?page_size=10&keyword=内容动作权限")
        assert public_list.status_code == 200
        assert public_list.json()["items"][0]["raw_content"] is None

        anonymous_admin_list = await client.get("/contents?page_size=10&keyword=内容动作权限&admin_view=true")
        assert anonymous_admin_list.status_code == 401

        user_admin_list = await client.get(
            "/contents?page_size=10&keyword=内容动作权限&admin_view=true",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_admin_list.status_code == 403

        admin_list = await client.get(
            "/contents?page_size=10&keyword=内容动作权限&admin_view=true",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_list.status_code == 200
        assert admin_list.json()["items"][0]["raw_content"] == "只有管理员应该看到的原文"

        admin_detail = await client.get(
            "/contents/1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_detail.status_code == 200
        assert admin_detail.json()["raw_content"] == "只有管理员应该看到的原文"

        anonymous_ignore = await client.post("/contents/1/ignore")
        assert anonymous_ignore.status_code == 401

        user_ignore = await client.post(
            "/contents/1/ignore?reason=seen",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_ignore.status_code == 200
        assert user_ignore.json() == {"content_id": 1, "ignored": True, "reason": "seen"}

        user_unignore = await client.delete(
            "/contents/1/ignore",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_unignore.status_code == 200
        assert user_unignore.json() == {"content_id": 1, "ignored": False, "removed": True}

        anonymous_enrich = await client.get("/contents/1/enrich")
        assert anonymous_enrich.status_code == 401

        user_enrich = await client.get(
            "/contents/1/enrich",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_enrich.status_code == 200
        assert user_enrich.json()["status"] == "completed"

        anonymous_batch = await client.post("/contents/enrich-batch?min_score=70&limit=10")
        assert anonymous_batch.status_code == 401

        user_batch = await client.post(
            "/contents/enrich-batch?min_score=70&limit=10",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert user_batch.status_code == 403

        admin_batch = await client.post(
            "/contents/enrich-batch?min_score=70&limit=10",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert admin_batch.status_code == 200
        assert admin_batch.json() == {"processed": [{"content_id": 2, "status": "completed"}]}

    await engine.dispose()


@pytest.mark.asyncio
async def test_single_enrich_skips_llm_when_claim_lost(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="content-claim-lost@example.com", password="Password123", role="user")
        user_token, _ = await create_session(db, user)
        db.add(
            ContentItem(
                id=1,
                title="增强认领失败样本",
                url="https://example.com/content-enrichment-claim-lost",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add(
            AiAnalysis(
                content_id=1,
                summary="测试摘要",
                curation_score=88,
                enrichment_status="pending",
            )
        )
        await db.commit()

    async def fake_claim(_repo: AnalysisRepository, content_id: int):
        return None

    async def fail_if_enrich_runs(content_id: int, db: AsyncSession):
        raise AssertionError("lost enrichment claim should not call LLM")

    monkeypatch.setattr(AnalysisRepository, "claim_enrichment_for_content", fake_claim)
    monkeypatch.setattr(enricher, "enrich_content", fail_if_enrich_runs)

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
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/contents/1/enrich",
            headers={"Authorization": f"Bearer {user_token}"},
        )

    assert response.status_code == 200
    assert response.json() == {"content_id": 1, "status": "processing", "enrichment": None}
    await engine.dispose()


@pytest.mark.asyncio
async def test_single_enrich_failure_persists_error_status(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="content-enrich-error@example.com", password="Password123", role="user")
        user_token, _ = await create_session(db, user)
        db.add(
            ContentItem(
                id=1,
                title="增强失败样本",
                url="https://example.com/content-enrichment-error",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        db.add(
            AiAnalysis(
                id=1,
                content_id=1,
                summary="测试摘要",
                curation_score=88,
                enrichment_status="pending",
            )
        )
        await db.commit()

    async def failing_enrich_content(content_id: int, db: AsyncSession):
        raise RuntimeError("temporary enrichment failure")

    monkeypatch.setattr(enricher, "enrich_content", failing_enrich_content)

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
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get(
            "/contents/1/enrich",
            headers={"Authorization": f"Bearer {user_token}"},
        )

    async with session_factory() as db:
        analysis = await db.get(AiAnalysis, 1)

    assert response.status_code == 500
    assert analysis.enrichment_status == "error"
    await engine.dispose()


@pytest.mark.asyncio
async def test_ignore_actions_use_sqlite_lock_retry(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as db:
        user = await create_user(db, email="content-retry@example.com", password="Password123", role="user")
        user_token, _ = await create_session(db, user)
        db.add(
            ContentItem(
                id=1,
                title="内容忽略重试样本",
                url="https://example.com/content-ignore-retry",
                source_name="测试信源",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
            )
        )
        await db.commit()

    retry_calls = 0

    async def retry_spy(operation, **kwargs):
        nonlocal retry_calls
        retry_calls += 1
        assert kwargs["attempts"] == 3
        assert kwargs["base_delay"] == 0.1
        assert kwargs["on_retry"] is not None
        return await operation()

    monkeypatch.setattr(contents_api, "retry_sqlite_locked", retry_spy)

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
    app.dependency_overrides[contents_api.get_db] = override_get_db

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        ignored = await client.post(
            "/contents/1/ignore?reason=seen",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert ignored.status_code == 200

        unignored = await client.delete(
            "/contents/1/ignore",
            headers={"Authorization": f"Bearer {user_token}"},
        )
        assert unignored.status_code == 200

    assert retry_calls == 2
    await engine.dispose()


# ── T1-4: content owner_user_id visibility ─────────────────────────────


@pytest.mark.asyncio
async def test_content_visibility_filter_excludes_other_users_private_content(monkeypatch):
    """User A's private content (from private source) must not leak into user B's list."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed: user A (id=10, pro), user B (id=11, free)
    user_a = User(
        id=10, email="a@example.com", password_hash="x", plan="pro", role="user", is_active=True, display_name="A"
    )
    user_b = User(
        id=11, email="b@example.com", password_hash="x", plan="free", role="user", is_active=True, display_name="B"
    )

    # Public source (admin) and private source for user A
    public_src = Source(
        id=1,
        name="Public",
        url="https://pub.com/rss",
        source_type=SourceType.RSS,
        owner_user_id=None,
        scope="system",
        status=SourceStatus.ACTIVE,
        weight=3,
        sort_order=0,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    private_src = Source(
        id=2,
        name="A-private",
        url="https://a.com/rss",
        source_type=SourceType.RSS,
        owner_user_id=10,
        scope="user",
        status=SourceStatus.ACTIVE,
        weight=3,
        sort_order=0,
        enabled=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    # Content from each source
    public_content = ContentItem(
        id=100,
        title="Public content",
        url="https://pub.com/1",
        source_id=1,
        source_name="Public",
        source_type="RSS",
        owner_user_id=None,
        status=ContentStatus.ANALYZED,
        content_hash="h1",
        crawled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    private_content = ContentItem(
        id=200,
        title="A private content",
        url="https://a.com/1",
        source_id=2,
        source_name="A-private",
        source_type="RSS",
        owner_user_id=10,
        status=ContentStatus.ANALYZED,
        content_hash="h2",
        crawled_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    async with session_factory() as db:
        db.add_all([user_a, user_b, public_src, private_src, public_content, private_content])
        await db.commit()

    # Build the app with dependency overrides
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

    app.dependency_overrides[contents_api.get_db] = override_get_db
    monkeypatch.setattr(contents_api, "async_session", session_factory)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # User A: should see public + own private
        app.dependency_overrides[auth_api.get_optional_current_user] = lambda: user_a
        resp_a = await client.get("/contents?page_size=10")
        assert resp_a.status_code == 200, resp_a.text
        ids_a = {item["id"] for item in resp_a.json()["items"]}
        assert 100 in ids_a, "user A should see public content"
        assert 200 in ids_a, "user A should see own private content"

        # User B: should see public, NOT user A's private
        app.dependency_overrides[auth_api.get_optional_current_user] = lambda: user_b
        resp_b = await client.get("/contents?page_size=10")
        assert resp_b.status_code == 200
        ids_b = {item["id"] for item in resp_b.json()["items"]}
        assert 100 in ids_b, "user B should see public content"
        assert 200 not in ids_b, "user B should NOT see user A's private content"

        # User B: GET user A's private content directly → 404
        resp_b_detail = await client.get("/contents/200")
        assert resp_b_detail.status_code == 404, "user B should not access user A's private content detail"

        # User A: GET own private content detail → 200
        app.dependency_overrides[auth_api.get_optional_current_user] = lambda: user_a
        resp_a_detail = await client.get("/contents/200")
        assert resp_a_detail.status_code == 200, "user A should access own private content detail"

    await engine.dispose()
