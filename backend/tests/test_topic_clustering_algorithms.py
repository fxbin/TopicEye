import pytest

from app.services import topic_clustering


@pytest.mark.asyncio
async def test_cluster_helpers_name_clusters(monkeypatch):
    async def fake_call_llm_json(prompt, **kwargs):
        return {"name": "AI工具", "summary": "工具更新"}

    monkeypatch.setattr(topic_clustering, "call_llm_json", fake_call_llm_json)

    clusters = [
        [
            {"id": 1, "title": "AI工具发布", "tags": ["AI", "工具"], "curation_score": 80},
            {"id": 2, "title": "AI工具上线", "tags": ["AI", "产品"], "curation_score": 70},
        ],
        [
            {"id": 3, "title": "模型更新", "tags": ["模型"], "curation_score": 75},
            {"id": 4, "title": "模型升级", "tags": ["模型"], "curation_score": 65},
        ],
    ]

    names = await topic_clustering._name_clusters(clusters)

    assert [item["name"] for item in names] == ["AI工具", "AI工具"]
    assert [item["content_count"] for item in names] == [2, 2]


@pytest.mark.asyncio
async def test_cluster_topics_with_lease_skips_active_run(monkeypatch):
    from app.services import job_tracker

    skipped_jobs = []

    async def fake_claim_job_run(job_key: str, name: str, description: str, timeout: int):
        return False

    async def fake_record_skipped_job(job_key: str, trigger_type: str, summary: str):
        skipped_jobs.append((job_key, trigger_type, summary))

    async def fail_cluster_topics(db):
        raise AssertionError("topic clustering body should be skipped while a lease is active")

    monkeypatch.setattr(job_tracker, "_claim_job_run", fake_claim_job_run)
    monkeypatch.setattr(job_tracker, "_record_skipped_job", fake_record_skipped_job)
    monkeypatch.setattr(topic_clustering, "cluster_topics", fail_cluster_topics)

    stats, claimed = await topic_clustering.cluster_topics_with_lease(
        None,
        trigger_type="manual",
    )

    assert stats is None
    assert claimed is False
    assert skipped_jobs == [(topic_clustering.TOPIC_CLUSTERING_JOB_KEY, "manual", "话题聚类仍在运行，本次触发已跳过")]


@pytest.mark.asyncio
async def test_cluster_topics_commits_in_batches_and_assigns_all_items(monkeypatch):
    """回归 #155：写回按 _TOPIC_COMMIT_BATCH 分批提交后，多批路径仍完整落库。"""
    from datetime import UTC, datetime

    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.database import Base
    from app.models.analysis import AiAnalysis
    from app.models.content import ContentItem, ContentStatus
    from app.models.topic import TopicGroup

    monkeypatch.setattr(topic_clustering, "_TOPIC_COMMIT_BATCH", 1)  # 2 组 → 强制中途 commit

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    now = datetime.now(UTC)
    try:
        async with session_factory() as db:
            content_id = 0
            for tag_a, tag_b in (("alpha", "beta"), ("gamma", "delta")):
                for _ in range(2):
                    content_id += 1
                    db.add(
                        ContentItem(
                            id=content_id,
                            title=f"话题聚类样例 {content_id}",
                            url=f"https://example.com/topic/{content_id}",
                            status=ContentStatus.ANALYZED,
                            crawled_at=now,
                        )
                    )
                    db.add(
                        AiAnalysis(
                            id=content_id,
                            content_id=content_id,
                            tags=[tag_a, tag_b],
                            curation_score=70,
                            created_at=now,
                        )
                    )
            await db.commit()

            stats = await topic_clustering.cluster_topics(db, use_llm_naming=False)

            assert stats["clusters"] == 2
            assert stats["total"] == 4
            assert set(stats["stage_ms"]) == {"fetch", "cluster_name", "write"}

            topics = (await db.execute(select(TopicGroup))).scalars().all()
            assert len(topics) == 2

            items = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()
            assert all(item.topic_id is not None for item in items)
            assert {item.topic_id for item in items} == {t.id for t in topics}
    finally:
        await engine.dispose()
