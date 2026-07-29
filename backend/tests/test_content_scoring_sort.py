from datetime import datetime
from types import SimpleNamespace

import pytest

from app.api.v1 import contents as contents_api
from app.services.scoring_engine import ScoreBreakdown, ScoringInput


class FakeContentRepo:
    def __init__(self, db):
        self.db = db

    async def list_for_scoring(
        self,
        *,
        filters,
        exclude_ids,
        exclude_source_types,
        time_cutoff,
        limit,
        visible_user_id=None,
        public_only=False,
    ):
        items = [
            _content_item(1, "high"),
            _content_item(2, "low"),
            _content_item(3, "middle"),
        ]
        return items, len(items)


def _content_item(content_id: int, title: str):
    timestamp = datetime(2026, 6, 8, 0, 0, 0)
    analysis = SimpleNamespace(
        id=content_id,
        content_id=content_id,
        created_at=timestamp,
        summary="",
        quality_score=0,
        hot_score=0,
        freshness_score=0,
        creator_score=0,
        viral_score=0,
        risk_score=0,
        curation_score=0,
        tags=[],
        recommendation=None,
        info_density=0,
        actionability=0,
        source_weight=0,
        enrichment_status="pending",
        enrichment=None,
    )
    return SimpleNamespace(
        id=content_id,
        title=title,
        url=f"https://example.com/{title}",
        source_id=1,
        source_name="测试信源",
        source_type="RSS",
        platform="rss",
        author=None,
        published_at=None,
        crawled_at=timestamp,
        content_hash=None,
        summary=None,
        raw_content=None,
        cover_url=None,
        category="AI",
        tags=[],
        language="zh",
        status="analyzed",
        is_favorited=False,
        created_at=timestamp,
        updated_at=timestamp,
        topic_id=None,
        analyses=[analysis],
    )


def _breakdown(content_id: int, final_score: float):
    return ScoreBreakdown(
        content_id=content_id,
        base_score=final_score,
        source_bonus=0,
        quality_factor=1,
        risk_factor=1,
        time_decay=1,
        diversity_factor=1,
        final_score=final_score,
        dimension_scores={},
        selected=True,
        threshold_used=0,
    )


async def _fake_build_scoring_inputs(db, items):
    scoring_inputs = [ScoringInput(content_id=item.id, title=item.title) for item in items]
    return scoring_inputs, {item.id: item for item in items}, {}


def _fake_score_items(scoring_inputs):
    scores = {1: 90.0, 2: 30.0, 3: 60.0}
    scored = [(_breakdown(item.content_id, scores[item.content_id]), item) for item in scoring_inputs]
    return [scored[2], scored[0], scored[1]]


@pytest.mark.asyncio
async def test_score_content_page_applies_ascending_order_before_pagination(monkeypatch):
    monkeypatch.setattr(contents_api, "ContentRepo", FakeContentRepo)
    monkeypatch.setattr("app.services.scoring_inputs.build_scoring_inputs", _fake_build_scoring_inputs)

    payload = await contents_api._score_content_page(
        db=object(),
        filters={},
        ignored_ids=[],
        time_cutoff=None,
        exclude_source_types=None,
        page=1,
        page_size=2,
        score_fn=_fake_score_items,
        sort_order="asc",
    )

    assert [item["id"] for item in payload["items"]] == [2, 3]
    assert [item["analysis"]["adjusted_curation_score"] for item in payload["items"]] == [30.0, 60.0]


@pytest.mark.asyncio
async def test_score_content_page_applies_descending_order_before_pagination(monkeypatch):
    monkeypatch.setattr(contents_api, "ContentRepo", FakeContentRepo)
    monkeypatch.setattr("app.services.scoring_inputs.build_scoring_inputs", _fake_build_scoring_inputs)

    payload = await contents_api._score_content_page(
        db=object(),
        filters={},
        ignored_ids=[],
        time_cutoff=None,
        exclude_source_types=None,
        page=1,
        page_size=2,
        score_fn=_fake_score_items,
        sort_order="desc",
    )

    assert [item["id"] for item in payload["items"]] == [1, 3]
    assert [item["analysis"]["adjusted_curation_score"] for item in payload["items"]] == [90.0, 60.0]
