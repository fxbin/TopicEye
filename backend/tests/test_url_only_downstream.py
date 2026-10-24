"""The source-evidence gate must survive every downstream model/read seam."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.api.v1 import contents as contents_api
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem, ContentStatus
from app.models.topic import TopicGroup
from app.models.trend import TopicTrend, TopicTrendMember
from app.repositories.content_event_consumption_repo import EventAssignment
from app.services import enricher, topic_clustering
from app.services.scoring_engine import ScoringInput
from app.services.scoring_event_selection import event_candidate_ids
from app.services.trends import snapshot_daily_trends

URL = "https://x.com/dexhorthy/status/2113841882602303540"
PLACEHOLDER = "🔗 阅读原文 via AIHOT · https://aihot.news/items/example"
BODY = "新工具提供可复现的编码测试。开发者可以检查实测结果。"


async def seed(db, *, body=None, topic_id=None, tags=None):
    item = ContentItem(
        title=URL, url=URL, summary=PLACEHOLDER, raw_content=body, topic_id=topic_id, status=ContentStatus.ANALYZED
    )
    db.add(item)
    await db.flush()
    analysis = AiAnalysis(
        content_id=item.id,
        summary="旧的无依据模型评价",
        summary_source="llm_pro",
        curation_score=99,
        quality_score=99,
        info_density=99,
        actionability=99,
        creator_score=99,
        viral_score=99,
        freshness_score=99,
        risk_score=0,
        source_weight=99,
        tags=tags or ["agents", "coding"],
        enrichment_status="pending",
    )
    db.add(analysis)
    await db.commit()
    return item, analysis


@pytest.mark.asyncio
@pytest.mark.parametrize("with_body", [False, True])
async def test_topic_naming_only_receives_readable_captured_items(db, monkeypatch, with_body):
    await seed(db, body=BODY if with_body else None)
    await seed(db, body=BODY if with_body else None)
    call = AsyncMock(return_value={"name": "编码工具测试", "summary": "实测方法"})
    monkeypatch.setattr(topic_clustering, "call_llm_json", call)
    stats = await topic_clustering.cluster_topics(db, use_llm_naming=True)
    assert stats["total"] == (2 if with_body else 0)
    assert call.await_count == (1 if with_body else 0)
    if with_body:
        prompt = str(call.await_args.args[0])
        assert BODY.split("。")[0] in prompt and URL not in prompt


@pytest.mark.asyncio
async def test_direct_enrichment_rejects_empty_source_without_model(db, monkeypatch):
    item, _ = await seed(db)
    call = AsyncMock(side_effect=AssertionError("must not call model"))
    monkeypatch.setattr(enricher, "call_llm_json", call)
    with pytest.raises(ValueError, match="no_readable_content"):
        await enricher.enrich_content(item.id, db)
    call.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "completed", "processing"])
async def test_enrichment_http_rejects_before_old_cache_or_claim(db, monkeypatch, status):
    item, analysis = await seed(db)
    analysis.enrichment_status = status
    analysis.enrichment = {"why_matters": "旧的错误增强"}
    await db.commit()
    call = AsyncMock(side_effect=AssertionError("must not enrich"))
    monkeypatch.setattr(enricher, "enrich_content", call)
    with pytest.raises(HTTPException) as error:
        await contents_api.get_enrichment(item.id, db=db, current_user=object())
    assert error.value.status_code == 422
    assert "原文" in error.value.detail
    assert analysis.enrichment_status == status
    call.assert_not_awaited()


@pytest.mark.asyncio
async def test_enrichment_filters_empty_related_context_and_uses_source_title(db, monkeypatch):
    topic = TopicGroup(name="同主题")
    db.add(topic)
    await db.commit()
    item, _ = await seed(db, body=BODY, topic_id=topic.id)
    await seed(db, topic_id=topic.id)
    call = AsyncMock(return_value={"why_matters": "真实正文可以分析"})
    monkeypatch.setattr(enricher, "call_llm_json", call)
    result = await enricher.enrich_content(item.id, db)
    assert result["related_items"] == []
    prompt = str(call.await_args.args[0])
    assert BODY.split("。")[0] in prompt and URL not in prompt


@pytest.mark.asyncio
async def test_new_trend_snapshots_only_freeze_readable_source_rows(db):
    topic = TopicGroup(name="候选主题")
    db.add(topic)
    await db.commit()
    bad, _ = await seed(db, topic_id=topic.id, tags=["empty-only"])
    good, _ = await seed(db, body=BODY, topic_id=topic.id, tags=["real-only"])
    stats = await snapshot_daily_trends(db, target_date=datetime.now(UTC).date())
    await db.commit()
    members = (await db.execute(select(TopicTrendMember))).scalars().all()
    assert members and {member.content_id for member in members} == {good.id}
    assert all(member.content_id != bad.id for member in members)
    assert all(member.title_snapshot == BODY.split("。")[0] + "。" for member in members)
    snapshots = (await db.execute(select(TopicTrend))).scalars().all()
    assert stats["topics"] == stats["keywords"] == 1
    assert all(snapshot.calculation_version == "trend-v4" for snapshot in snapshots)
    assert all(snapshot.keyword != "empty-only" for snapshot in snapshots)


def test_metrics_can_use_readable_member_when_canonical_has_no_evidence():
    bad = ScoringInput(content_id=1, content_evidence=False, curation_score=99)
    good = ScoringInput(content_id=2, content_evidence=True, curation_score=80)
    assignments = {1: EventAssignment(1, 10, 1, True), 2: EventAssignment(2, 10, 1, False)}
    assert event_candidate_ids([bad, good], assignments) == {2}
    assert assignments[2].canonical_content_id == 1
