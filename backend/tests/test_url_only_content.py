"""Regress the actual AIHOT URL-title/high-score failure without live calls."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.schemas.content import ContentResponse
from app.services import analysis, today_picks
from app.services.llm_pre_filter import should_skip_analysis
from app.services.scoring_engine import score_items
from app.services.scoring_inputs import build_scoring_input

URL = "https://x.com/dexhorthy/status/2113841882602303540"
PLACEHOLDER = "🔗 阅读原文 via AIHOT · https://aihot.news/items/r97x057olit37no2h6x3pbulu"
BODY = "新工具支持本地运行编码代理，并提供可复现的测试步骤。开发者可以直接检查运行日志和测试结果。"


def row(**updates):
    now = datetime.now(UTC)
    data = {
        "id": 37111,
        "platform": None,
        "title": URL,
        "url": "https://aihot.news/items/example",
        "summary": PLACEHOLDER,
        "raw_content": None,
        "source_id": 1,
        "source_name": "AIHOT",
        "category": "AI",
        "published_at": now,
        "crawled_at": now,
        "created_at": now,
        "updated_at": now,
        "status": "analyzed",
        "source_weight_db": 5,
        "summary_source": "llm_pro",
        "curation_score": 99,
        "quality_score": 99,
        "info_density": 99,
        "actionability": 99,
        "creator_score": 99,
        "viral_score": 99,
        "freshness_score": 99,
        "risk_score": 0,
        "hot_score": 99,
        "analysis_source_weight": 99,
        "ai_summary": "一手技术重大发布",
        "recommendation": "模型生成的高评价不算原文证据",
    }
    data.update(updates)
    return data


@pytest.mark.parametrize(
    "summary,raw",
    [
        ("", None),
        (PLACEHOLDER, None),
        (
            '<p><a href="https://example.com">阅读原文</a></p>',
            '<div><a href="https://example.com">https://example.com</a></div>',
        ),
        ("[Read more](https://example.com)", None),
        ("Article URL: https://example.com", None),
    ],
)
def test_link_only_input_is_skipped(summary, raw):
    assert should_skip_analysis(SimpleNamespace(title=URL, summary=summary, raw_content=raw)) == (
        True,
        "no_readable_content",
    )


def test_legacy_high_score_does_not_enter_picks_or_raise_percentile():
    bad = row()
    good = row(id=2, title="有实测与方法的编码工具发布", summary=BODY, source_id=2, curation_score=75)
    baseline = today_picks._score_rows([good])
    actual = today_picks._score_rows([bad, good])
    assert [r["id"] for _, r in actual] == [2]
    assert actual[0][0].to_dict() == baseline[0][0].to_dict()


def test_shared_orm_scoring_rejects_legacy_url_only_analysis():
    data = row()
    item = SimpleNamespace(
        **data,
        source=SimpleNamespace(weight=5),
        analyses=[SimpleNamespace(**{**data, "id": 38231, "source_weight": 99})],
    )
    assert score_items([build_scoring_input(item)]) == []


@pytest.mark.parametrize("raw,expected", [(None, "原文待补全"), (f"<p>{BODY}</p>", BODY.split("。")[0] + "。")])
def test_legacy_response_title_uses_source_body_or_explicit_placeholder(raw, expected):
    payload = ContentResponse.model_validate(row(raw_content=raw)).model_dump()
    assert payload["title"] == expected
    assert payload["url"] == "https://aihot.news/items/example"


@pytest.mark.asyncio
async def test_direct_analysis_rejects_url_only_without_model_call(monkeypatch):
    call = AsyncMock(side_effect=AssertionError("must not call model"))
    monkeypatch.setattr(analysis, "_call_llm_json_with_metadata", call)
    with pytest.raises(ValueError, match="no_readable_content"):
        await analysis.analyze_content(SimpleNamespace(**row()), AsyncMock())
    call.assert_not_awaited()


def test_url_title_with_real_body_stays_eligible_and_displays_body_title():
    scored = today_picks._score_rows([row(raw_content=f"<p>{BODY}</p>")])
    assert len(scored) == 1
    bd, source = scored[0]
    assert today_picks._row_to_content_payload(source, bd)["title"] == BODY.split("。")[0] + "。"


@pytest.mark.parametrize(
    "title,summary,raw",
    [
        ("Claude 发布新版本", "", None),
        ("How to use the API https://example.com/docs", "", None),
        (URL, BODY, None),
        (URL, "", f"<article><p>{BODY}</p></article>"),
    ],
)
def test_real_source_text_is_not_rejected_by_curation(title, summary, raw):
    assert len(today_picks._score_rows([row(title=title, summary=summary, raw_content=raw)])) == 1


@pytest.mark.asyncio
async def test_claimed_legacy_link_is_marked_skipped_without_retry(db, monkeypatch):
    from app.models.content import ContentItem, ContentStatus
    from app.repositories.content_repo import ContentRepo

    item = ContentItem(title=URL, summary=PLACEHOLDER, url="https://example.com/old", status=ContentStatus.PENDING)
    db.add(item)
    await db.commit()
    call = AsyncMock(side_effect=AssertionError("must not analyze"))
    result = await analysis.analyze_one_claimed(item.id, db, analyzer=call)
    assert result is None
    call.assert_not_awaited()
    await db.refresh(item)
    assert item.skip_analysis is True
    assert item.skip_reason == "no_readable_content"
    assert item.status == ContentStatus.PENDING
    assert item.analysis_claim_token is None
    assert item.analysis_lease_expires_at is None
    assert item.analysis_next_retry_at is None
    assert await ContentRepo(db).claim_analysis_job(item.id) is None


@pytest.mark.asyncio
async def test_stale_worker_cannot_mark_new_owner_skipped(db):
    from app.models.content import ContentItem, ContentStatus
    from app.repositories.content_repo import ContentRepo

    item = ContentItem(title=URL, url=URL, status=ContentStatus.ANALYZING, analysis_claim_token="new-owner")
    db.add(item)
    await db.commit()
    assert not await ContentRepo(db).skip_analysis_claim(item.id, "old-owner", reason="no_readable_content")
    await db.refresh(item)
    assert not item.skip_analysis
    assert item.analysis_claim_token == "new-owner"


@pytest.mark.asyncio
async def test_ingestion_skips_placeholders_and_repairs_title_without_changing_hash(db, monkeypatch):
    from sqlalchemy import select

    from app.models.content import ContentItem
    from app.models.source import Source, SourceType
    from app.services import content_pipeline
    from app.services.dedup import build_hash

    class FakeScraper:
        def __init__(self, **kwargs):
            pass

        async def fetch(self, client):
            return [
                {"title": URL, "url": "https://example.com/missing", "summary": PLACEHOLDER},
                {"title": URL, "url": "https://example.com/body", "summary": PLACEHOLDER, "raw_content": BODY},
            ]

    classify = AsyncMock(return_value={"category": "AI", "tags": [], "is_new_category": False, "confidence": 0.8})
    monkeypatch.setattr(content_pipeline, "get_scraper_cls", lambda _: FakeScraper)
    monkeypatch.setattr(content_pipeline, "_get_active_category_names", AsyncMock(return_value=["AI"]))
    monkeypatch.setattr(content_pipeline, "classify_entry_readonly", classify)
    source = Source(name="Fixture RSS", url="https://example.com/feed", source_type=SourceType.RSS, enabled=True)
    db.add(source)
    await db.commit()
    result = await content_pipeline.ingest_from_source(source, db)
    assert result["new"] == 2
    items = (await db.execute(select(ContentItem).order_by(ContentItem.id))).scalars().all()
    assert items[0].skip_analysis and items[0].skip_reason == "no_readable_content"
    assert items[0].title == URL
    assert not items[1].skip_analysis
    assert items[1].title == BODY.split("。")[0] + "。"
    assert items[1].content_hash == build_hash(URL + "https://example.com/body")
    classify.assert_awaited_once()
    assert classify.await_args.args[0] == items[1].title


@pytest.mark.asyncio
async def test_picks_rejects_legacy_empty_canonical_before_representative_selection(monkeypatch):
    from app.repositories.content_event_consumption_repo import ContentEventConsumptionRepository, EventAssignment

    # Use a shared event with an accepted member; the unreadable canonical
    # must not suppress the readable report or inflate hidden-member counts.
    bad = row(id=1)
    good = row(id=2, title="有效的事件报道", summary=BODY)
    assignments = {
        1: EventAssignment(1, 10, 1, True, canonical_locked=True),
        2: EventAssignment(2, 10, 1, False, canonical_locked=True),
    }

    async def run(fn):
        return fn()

    monkeypatch.setattr(today_picks, "run_query", run)
    monkeypatch.setattr(today_picks, "query_today_picks", lambda **kw: [bad, good])
    monkeypatch.setattr(today_picks, "query_topics", lambda **kw: [])
    monkeypatch.setattr(
        ContentEventConsumptionRepository, "resolve_today_pick_assignments", AsyncMock(return_value=assignments)
    )
    monkeypatch.setattr(ContentEventConsumptionRepository, "load_display_groups", AsyncMock(return_value={}))
    payload = await today_picks.build_today_picks(object(), limit=1)
    assert [item["id"] for item in payload["items"]] == [2]
    assert payload["total"] == 1
    assert payload["event_members_hidden"] == 0
    assert payload["pending_review"]["total"] == 0


@pytest.mark.asyncio
async def test_postgres_legacy_rows_are_gated_in_picks_report_and_enrichment(monkeypatch):
    from datetime import timedelta

    from app.core.database import async_session
    from app.models.analysis import AiAnalysis
    from app.models.content import ContentItem, ContentStatus
    from app.models.source import Source, SourceType
    from app.repositories.content_repo import ContentRepo
    from app.services.daily_report import _fetch_report_inputs
    from app.services.enrichment_selection import get_pending_enrichment_ids
    from app.services.scoring_flow import build_scoring_inputs_from_rows

    async with async_session() as db:
        source = Source(
            name="AIHOT regression", url="https://example.com/regression", source_type=SourceType.RSS, weight=5
        )
        db.add(source)
        await db.flush()
        bad = ContentItem(
            title=URL,
            url=URL,
            summary=PLACEHOLDER,
            source_id=source.id,
            source_name=source.name,
            status=ContentStatus.ANALYZED,
        )
        good = ContentItem(
            title=URL,
            url="https://example.com/real",
            summary=PLACEHOLDER,
            raw_content=BODY,
            source_id=source.id,
            source_name=source.name,
            status=ContentStatus.ANALYZED,
        )
        db.add_all([bad, good])
        await db.flush()
        for item in [bad, good]:
            db.add(
                AiAnalysis(
                    content_id=item.id,
                    curation_score=99,
                    quality_score=99,
                    creator_score=99,
                    viral_score=99,
                    info_density=99,
                    actionability=99,
                    freshness_score=99,
                    source_weight=99,
                    risk_score=0,
                    summary="不应作为原始证据的模型描述",
                    summary_source="llm_pro",
                    enrichment_status="pending",
                )
            )
        await db.commit()

        async def unavailable(_fn):
            raise RuntimeError("test forces real PostgreSQL fallback")

        monkeypatch.setattr(today_picks, "run_query", unavailable)
        payload = await today_picks.build_today_picks(db, hours=24, limit=10)
        assert [item["id"] for item in payload["items"]] == [good.id]
        assert payload["items"][0]["title"] == BODY.split("。")[0] + "。"
        assert payload["total"] == 1
        assert await get_pending_enrichment_ids(db, min_score=0, limit=10) == [good.id]

        rows = await ContentRepo(db).list_scoring_rows()
        assert next(r for r in rows if r.id == good.id).raw_content == BODY
        inputs, _, _ = await build_scoring_inputs_from_rows(db, rows)
        assert [item.content_id for _, item in score_items(inputs)] == [good.id]

        local_now = (datetime.now(UTC) + timedelta(hours=8)).replace(tzinfo=None)
        curated, background = await _fetch_report_inputs(
            db, window_start=local_now - timedelta(days=1), window_end=local_now + timedelta(days=1)
        )
        assert [item["id"] for item in curated] == [good.id]
        assert [item["id"] for item in background] == [good.id]
        assert curated[0]["title"] == BODY.split("。")[0] + "。"


@pytest.mark.asyncio
@pytest.mark.parametrize("existing_analysis", [False, True])
async def test_manual_analysis_reports_missing_source_instead_of_running_or_old_score(
    db, monkeypatch, existing_analysis
):
    from fastapi import HTTPException

    from app.api.v1 import analyses as analyses_api
    from app.models.analysis import AiAnalysis
    from app.models.content import ContentItem, ContentStatus

    item = ContentItem(
        title=URL,
        url=URL,
        summary=PLACEHOLDER,
        status=ContentStatus.ANALYZED if existing_analysis else ContentStatus.PENDING,
    )
    db.add(item)
    await db.flush()
    if existing_analysis:
        db.add(AiAnalysis(content_id=item.id, curation_score=99, summary="旧的无依据高评价"))
    await db.commit()
    model = AsyncMock(side_effect=AssertionError("must not call model"))
    monkeypatch.setattr(analyses_api, "analyze_content", model)
    with pytest.raises(HTTPException) as error:
        await analyses_api.analyze_single(item.id, db=db)
    assert error.value.status_code == 422
    assert "原文" in error.value.detail
    model.assert_not_awaited()
    assert item.analysis_attempts == 0
