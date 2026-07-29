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
