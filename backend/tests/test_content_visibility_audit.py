"""Owner checks must hold at every content exit, before a model call or write."""

from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.api.v1 import analyses, auth, contents, creation, favorites, feedback, topics
from app.core.database import get_db
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.content_relation import ContentRelation
from app.models.creation import CreationPlan
from app.models.topic import TopicGroup
from app.models.user import User
from app.services import creation as fast_service, creation_explore, interest_vector_service


@pytest_asyncio.fixture
async def scoped_content_client(test_session_factory, monkeypatch):
    async with test_session_factory() as db:
        users = [User(id=1, email="owner-a@test"), User(id=2, email="owner-b@test")]
        db.add_all(users)
        db.add_all(
            [
                TopicGroup(id=1, name="公共话题"),
                TopicGroup(id=2, name="私有话题"),
                TopicGroup(id=3, name="混合私有摘要"),
            ]
        )
        await db.flush()
        # 1 public, 2 own, 3 foreign; mixed group 3 contains both public and foreign.
        for cid, owner, tid in [(1, None, 1), (2, 1, 2), (3, 2, 2), (4, None, 3), (5, 2, 3)]:
            db.add(
                ContentItem(
                    id=cid,
                    title=f"文章{cid}",
                    url=f"https://example.test/{cid}",
                    source_name="测试源",
                    source_type="RSS",
                    owner_user_id=owner,
                    topic_id=tid,
                    status=ContentStatus.ANALYZED,
                )
            )
            await db.flush()
            db.add(
                AiAnalysis(
                    content_id=cid,
                    summary=f"摘要{cid}",
                    key_points=["事实"],
                    tags=["评估", "工作流"],
                    curation_score=90,
                    enrichment_status="completed",
                    enrichment={"background": f"增强{cid}"},
                )
            )
        db.add_all(
            [
                ContentRelation(source_id=1, target_id=2, relation_type="related", confidence=0.8),
                ContentRelation(source_id=1, target_id=3, relation_type="related", confidence=0.9),
            ]
        )
        await db.commit()

    calls = []

    async def fake_llm(*args, **kwargs):
        calls.append(kwargs.get("scene"))
        return {"titles": ["测试方案"], "outline": ["结构"], "assumptions": [], "question": "目标读者是谁？"}

    monkeypatch.setattr(fast_service, "call_llm_json", fake_llm)
    monkeypatch.setattr(creation_explore, "call_llm_json", fake_llm)
    monkeypatch.setattr(creation, "async_session", test_session_factory)
    monkeypatch.setattr(interest_vector_service, "trigger_vector_rebuild", lambda _: None)
    app = FastAPI()
    for router in [analyses.router, contents.router, creation.router, favorites.router, feedback.router, topics.router]:
        app.include_router(router)

    async def session_override():
        async with test_session_factory() as db:
            try:
                yield db
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    app.dependency_overrides[get_db] = session_override
    app.dependency_overrides[auth.get_current_user] = lambda: users[0]
    app.dependency_overrides[auth.get_optional_current_user] = lambda: users[0]
    from app.services.json_cache import invalidate_json_cache

    invalidate_json_cache()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        yield client, calls, test_session_factory, app
    invalidate_json_cache()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("GET", "/analyses/content/3", None),
        ("POST", "/analyses/content/3", None),
        ("GET", "/contents/3/enrich", None),
        ("POST", "/contents/3/favorite", None),
        ("POST", "/contents/3/ignore", None),
        ("POST", "/favorites", {"target_type": "content", "target_id": 3}),
        ("POST", "/feedback", {"content_id": 3, "feedback_type": "like"}),
        ("GET", "/contents/3/relations", None),
    ],
)
async def test_content_exits_reject_other_users_private_content(scoped_content_client, method, path, body):
    client, calls, _, _ = scoped_content_client
    response = await client.request(method, path, json=body)
    assert response.status_code == 404, response.text
    assert not calls


@pytest.mark.asyncio
async def test_analysis_list_filters_data_and_total(scoped_content_client):
    client, _, _, _ = scoped_content_client
    response = await client.get("/analyses?page_size=100")
    assert response.status_code == 200
    assert {item["content_id"] for item in response.json()["items"]} == {1, 2, 4}
    assert response.json()["total"] == 3
    page = await client.get("/analyses?page=2&page_size=2")
    assert page.json()["total"] == 3
    assert len(page.json()["items"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cid", [1, 2])
async def test_analysis_and_enrichment_allow_public_and_own(scoped_content_client, cid):
    client, _, _, _ = scoped_content_client
    for method, path in [
        ("GET", f"/analyses/content/{cid}"),
        ("POST", f"/analyses/content/{cid}"),
        ("GET", f"/contents/{cid}/enrich"),
    ]:
        response = await client.request(method, path)
        assert response.status_code == 200, response.text


def phase_payload(phase, content_id):
    return {
        "plan": {"content_id": content_id, "platform": "wechat"},
        "explore": {"content_id": content_id},
        "focus": {"content_id": content_id, "selected_direction": "方向"},
        "converge": {"content_id": content_id, "platform": "wechat", "selected_direction": "方向", "focus_answers": []},
    }[phase]


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["plan", "explore", "focus", "converge"])
async def test_creation_rejects_foreign_content_before_llm(scoped_content_client, phase):
    client, calls, factory, _ = scoped_content_client
    response = await client.post(f"/creation/{phase}", json=phase_payload(phase, 3))
    assert response.status_code == 400, response.text
    assert not calls
    async with factory() as db:
        assert not (await db.execute(select(CreationPlan))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["plan", "explore", "focus", "converge"])
@pytest.mark.parametrize("cid", [1, 2])
async def test_creation_allows_public_and_own_content(scoped_content_client, phase, cid):
    client, calls, _, _ = scoped_content_client
    response = await client.post(f"/creation/{phase}", json=phase_payload(phase, cid))
    assert response.status_code == 200, response.text
    assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["plan", "converge"])
async def test_successful_creation_survives_new_session(scoped_content_client, phase):
    client, _, factory, _ = scoped_content_client
    response = await client.post(f"/creation/{phase}", json=phase_payload(phase, 2))
    assert response.status_code == 200, response.text
    async with factory() as db:
        history = (await db.execute(select(CreationPlan))).scalars().all()
        assert len(history) == 1
        assert history[0].content_id == 2 and history[0].user_id == 1
    history_response = await client.get("/creation/plans")
    assert history_response.json()["count"] == 1


@pytest.mark.asyncio
async def test_relation_target_is_filtered_for_user_and_anonymous(scoped_content_client):
    client, _, _, app = scoped_content_client
    response = await client.get("/contents/1/relations")
    assert [r["target_id"] for r in response.json()["relations"]] == [2]
    app.dependency_overrides[auth.get_optional_current_user] = lambda: None
    response = await client.get("/contents/1/relations")
    assert response.json()["relations"] == []
    assert (await client.get("/contents/2/relations")).status_code == 404


@pytest.mark.asyncio
async def test_global_topics_expose_only_groups_without_private_members(scoped_content_client):
    client, _, _, _ = scoped_content_client
    listing = await client.get("/topics")
    assert listing.status_code == 200
    assert [t["id"] for t in listing.json()["items"]] == [1]
    assert listing.json()["total"] == 1
    assert (await client.get("/topics/2")).status_code == 404
    assert (await client.get("/topics/3")).status_code == 404
    assert (await client.get("/topics/1")).json()["items"][0]["id"] == 1


@pytest.mark.asyncio
async def test_clustering_never_uses_private_inputs_for_global_topics(db):
    from app.services.topic_clustering import cluster_topics

    db.add(User(id=1, email="private-cluster@test"))
    await db.flush()
    for cid in range(1, 5):
        db.add(
            ContentItem(
                id=cid,
                title=f"聚类样本{cid}",
                url=f"https://example.test/cluster/{cid}",
                source_type="RSS",
                status=ContentStatus.ANALYZED,
                owner_user_id=1 if cid > 2 else None,
            )
        )
        await db.flush()
        db.add(AiAnalysis(content_id=cid, tags=["alpha", "beta"], curation_score=70))
    await db.commit()
    stats = await cluster_topics(db, use_llm_naming=False)
    assert stats["total"] == 2
    assert stats["clusters"] == 1
    rows = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()
    assert rows[0].topic_id == rows[1].topic_id is not None
    assert rows[2].topic_id is None and rows[3].topic_id is None


def test_duckdb_topic_reads_exclude_private_and_mixed_metadata():
    import duckdb

    from app.services._duckdb_topics_mixin import TopicsMixin

    conn = duckdb.connect(":memory:")
    try:
        conn.execute("CREATE SCHEMA oltp_db")
        conn.execute("CREATE TABLE oltp_db.content_items (id BIGINT, topic_id BIGINT, owner_user_id BIGINT)")
        conn.execute("INSERT INTO oltp_db.content_items VALUES (1,1,NULL),(2,2,1),(3,3,NULL),(4,3,2)")
        conn.execute(
            "CREATE TABLE oltp_db.topic_groups (id BIGINT, name VARCHAR, summary VARCHAR, keywords JSON, best_score DOUBLE, content_count BIGINT)"
        )
        conn.execute(
            "INSERT INTO oltp_db.topic_groups VALUES (1,'公共','公开摘要','[]',80,1),(2,'私有','秘密摘要','[]',90,1),(3,'混合','混合秘密','[]',95,2)"
        )
        conn.execute(
            "CREATE TABLE oltp_db.topic_trends (id BIGINT, snapshot_date DATE, topic_id BIGINT, topic_name VARCHAR, content_count BIGINT, avg_score DOUBLE, max_score DOUBLE, pick_count BIGINT, top_items JSON, provenance_status VARCHAR, calculation_version VARCHAR, created_at TIMESTAMP)"
        )
        conn.execute(
            "INSERT INTO oltp_db.topic_trends SELECT id, current_date, id, name, content_count, 70, 80, 0, '[]', 'complete', 'trend-v4', current_timestamp FROM oltp_db.topic_groups"
        )

        class Analytics(TopicsMixin):
            def _get_conn(self):
                return conn

        analytics = Analytics()
        assert [t["id"] for t in analytics.query_topics()] == [1]
        assert [t["topic_id"] for t in analytics.query_trend_topics()] == [1]
    finally:
        conn.close()


@pytest.mark.asyncio
async def test_trend_snapshot_metadata_respects_public_group_scope(scoped_content_client):
    from datetime import UTC, date, datetime, timedelta

    from app.models.trend import TopicTrend
    from app.repositories.trend_repo import TrendRepository

    _, _, factory, _ = scoped_content_client
    async with factory() as db:
        for tid in (1, 2, 3):
            db.add(TopicTrend(topic_id=tid, snapshot_date=date.today(), topic_name=f"话题{tid}", content_count=1))
        await db.commit()
        repo = TrendRepository(db)
        assert await repo.get_topic_snapshot(1, date.today()) is not None
        assert await repo.get_topic_snapshot(2, date.today()) is None
        assert await repo.get_topic_snapshot(3, date.today()) is None
        now = datetime.now(UTC)
        candidates = await repo.list_topic_snapshot_candidates(now - timedelta(days=1), now + timedelta(days=1))
        assert {r.id for r in candidates} == {1}


@pytest.mark.asyncio
async def test_postgres_visibility_queries_use_transaction_owner():
    """Exercise the same SQL on disposable PG, in addition to SQLite HTTP tests."""
    from app.core.database import async_session
    from app.repositories.analysis_repo import AnalysisRepository
    from app.repositories.content_repo import ContentRepo

    async with async_session() as db:
        db.add_all([User(id=1, email="pg-owner-a@test"), User(id=2, email="pg-owner-b@test")])
        await db.flush()
        for cid, owner in [(1, None), (2, 1), (3, 2)]:
            db.add(
                ContentItem(
                    id=cid,
                    title=f"PG样本{cid}",
                    url=f"https://example.test/pg/{cid}",
                    source_type="RSS",
                    owner_user_id=owner,
                )
            )
            await db.flush()
            db.add(AiAnalysis(content_id=cid, summary=f"PG摘要{cid}"))
        await db.commit()
        repo = AnalysisRepository(db)
        assert await ContentRepo(db).get_visible_by_id(3, 1) is None
        assert await repo.get_visible_content_and_analysis(3, 1) is None
        assert await repo.get_visible_content_and_analysis(2, 1) is not None
        assert await repo.get_visible_content_and_analysis(2) is None
        rows, total = await repo.list_with_score_filter(visible_user_id=1)
        assert total == 2
        assert {row.content_id for row in rows} == {1, 2}
