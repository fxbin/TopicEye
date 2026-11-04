"""Editorial regressions use deterministic replay, never a real provider."""

import pytest

from app.services.daily_report import _match_picks_to_curated
from app.services.digest_fallback import build_daily_editorial_fallback


def material(**changes):
    return {
        "id": 7,
        "title": "Langfuse：不只评测模型，还要审核AI应用",
        "url": "https://example.com/langfuse",
        "category": "技巧观点",
        "summary": "文章讨论应用级审核需要覆盖实际工作流。",
        "recommendation": "可用一条实际工作流说明应用审核与模型评测的区别。",
        "adjusted_score": 87,
        "curation_score": 87,
        "source_name": "技术观察",
        "creator_score": 87,
        "viral_score": 75,
        "quality_score": 85,
        "risk_score": 0,
        **changes,
    }


def test_daily_report_quality_replaces_leaked_title_template_and_internal_reference(caplog):
    item = material()
    picks, ids = _match_picks_to_curated(
        [
            {
                "source_idx": 1,
                "editorial_title": "X的真正问题不是Y，是Z：Langfuse银行认证AI应用",
                "reason": "结合#10 Siri开放，揭示模型与应用分离趋势",
                "tier": "brief",
            },
        ],
        [item],
    )
    assert ids == [7]
    assert picks[0]["title"] == item["title"]
    assert "#10" not in picks[0]["reason"]
    assert item["summary"] in picks[0]["reason"]
    assert caplog.records, "editorial fallback must not be silent"


def test_daily_report_quality_source_identity_is_owned_by_selected_material():
    item = material()
    picks, _ = _match_picks_to_curated(
        [
            {
                "source_idx": 1,
                "source_title": "另一家公司融资消息",
                "editorial_title": "另一家公司计划IPO",
                "reason": "与对应素材无关的判断",
            },
        ],
        [item],
    )
    assert picks[0]["source_title"] == item["title"]
    assert picks[0]["title"] == item["title"]
    assert "IPO" not in picks[0]["reason"]


def test_daily_report_quality_rejects_explicit_invalid_index_instead_of_rebinding_by_title():
    item = material()
    picks, ids = _match_picks_to_curated(
        [
            {"source_idx": 9, "source_title": item["title"], "reason": "看似能匹配的标题"},
        ],
        [item],
    )
    assert picks == []
    assert ids == []


def test_daily_report_quality_does_not_repeat_a_material_as_multiple_picks():
    item = material()
    pick = {"source_idx": 1, "editorial_title": item["title"], "reason": "讨论应用审核的验证范围。"}
    picks, ids = _match_picks_to_curated([pick, dict(pick)], [item])
    assert len(picks) == 1
    assert ids == [7]


def test_daily_report_quality_skips_malformed_picks_without_failing_valid_neighbors():
    item = material()
    picks, ids = _match_picks_to_curated([None, "bad", {"source_idx": 1, "reason": "应用审核的验证范围。"}], [item])
    assert len(picks) == 1
    assert ids == [7]


def test_daily_report_quality_preserves_real_x_entity_and_external_issue_number():
    item = material(title="X发布新接口，GitHub issue #119记录迁移问题")
    picks, _ = _match_picks_to_curated(
        [
            {
                "source_idx": 1,
                "editorial_title": "X接口迁移：先处理GitHub issue #119",
                "reason": "GitHub issue #119记录接口迁移问题。",
            },
        ],
        [item],
    )
    assert picks[0]["title"].startswith("X接口迁移")
    assert "#119" in picks[0]["reason"]


def test_daily_report_quality_fallback_uses_source_title_instead_of_a_generic_editorial_prefix():
    item = material()
    result = build_daily_editorial_fallback([item], label="测试日报")
    assert result["top_picks"][0]["editorial_title"] == item["title"]


def test_daily_report_quality_prompt_pool_contains_complete_units_and_binds_matchable_ids():
    from app.services.daily_report import _format_items, _prepare_prompt_pool

    first = material(title="支持JSON {schema}的应用评测")
    second = material(id=8, title="第二条素材", summary="不能出现一半的第二条素材" * 20)
    budget = len(_format_items([first], limit=1, selected=True)) + 1
    pool, text = _prepare_prompt_pool([first, second], limit=50, max_chars=budget, selected=True)
    assert pool == [first]
    assert "JSON {schema}" in text
    assert "第二条素材" not in text
    assert "truncated" not in text
    assert _match_picks_to_curated([{"source_idx": 2, "reason": "输入中不存在"}], pool) == ([], [])


def test_daily_report_quality_fallback_source_index_is_input_position_not_new_score_rank():
    low, high = material(id=1, adjusted_score=70), material(id=2, title="高分素材", adjusted_score=90)
    fallback = build_daily_editorial_fallback([low, high], label="日报")
    assert [p["source_idx"] for p in fallback["top_picks"]] == [2, 1]
    picks, ids = _match_picks_to_curated(fallback["top_picks"], [low, high])
    assert ids == [2, 1]
    assert [p["source_title"] for p in picks] == [high["title"], low["title"]]


def test_daily_report_quality_cleans_public_sections_but_keeps_real_external_references():
    from app.services.daily_report_editorial import review_daily_sections

    fallback = build_daily_editorial_fallback([material()], label="日报")
    result, issues = review_daily_sections(
        {
            "overview": "结合#10揭示趋势",
            "takeaway": "X这步决定了Y天花板",
            "trends": [None, {"title": "#22揭示的趋势"}, {"title": "GitHub issue #119迁移", "momentum": []}],
            "platform_tips": {"公众号": ["结合#10写一篇文章", "对照应用审核的具体步骤。"]},
        },
        fallback,
        "GitHub issue #119记录迁移问题",
    )
    assert issues
    assert result["overview"] == fallback["overview"]
    assert result["takeaway"] == fallback["takeaway"]
    assert len(result["trends"]) == 1
    assert result["trends"][0]["momentum"] == "stable"
    assert result["platform_tips"]["公众号"] == ["对照应用审核的具体步骤。"]


async def _generate_replay(monkeypatch, session_factory, response, *, background=None):
    from datetime import date, datetime
    from unittest.mock import AsyncMock

    from app.services import daily_report

    async def inputs(*_args, **_kwargs):
        return [material()], background if background is not None else [material()]

    monkeypatch.setattr(daily_report, "_fetch_report_inputs", inputs)
    monkeypatch.setattr(daily_report, "_local_now", lambda: datetime(2026, 11, 4, 12))
    monkeypatch.setattr(daily_report, "call_llm_json", AsyncMock(return_value=response))
    monkeypatch.setattr(daily_report, "_push_daily_report_success", AsyncMock())
    monkeypatch.setattr(daily_report, "_push_daily_report_failure", AsyncMock())
    async with session_factory() as db:
        report = await daily_report.generate_daily_report(db, target_date=date(2026, 11, 4), edition="noon")
        await db.refresh(report)
        return report


@pytest.mark.asyncio
async def test_daily_report_quality_replayed_bad_editorial_is_not_persisted(monkeypatch, test_session_factory):
    import json

    report = await _generate_replay(
        monkeypatch,
        test_session_factory,
        {
            "overview": "结合#10判断整体趋势",
            "takeaway": "X这步决定了Y天花板",
            "top_picks": [
                {
                    "source_idx": 1,
                    "tier": "feature",
                    "editorial_title": "X的真正问题不是Y，是Z：Langfuse",
                    "reason": "结合#10 Siri开放，利润将高于应用层",
                    "lifecycle": "见顶",
                }
            ],
            "trends": [{"title": "#22揭示的趋势"}],
        },
    )
    assert report.status == "DONE"
    for text in (report.overview, report.takeaway, report.top_picks, report.trends):
        assert "#10" not in text and "#22" not in text and "X的真正问题" not in text
    picks = json.loads(report.top_picks)
    assert picks[0]["title"] == material()["title"]
    assert picks[0]["content_id"] == 7
    assert picks[0]["tier"] == "brief" and "lifecycle" not in picks[0]
    assert "利润" not in picks[0]["reason"]


@pytest.mark.asyncio
async def test_daily_report_quality_empty_valid_selection_uses_visible_material_fallback(
    monkeypatch, test_session_factory
):
    import json

    report = await _generate_replay(
        monkeypatch,
        test_session_factory,
        {
            "overview": "可以阅读今日素材。",
            "takeaway": "应用审核",
            "top_picks": [{"source_idx": 99}],
        },
    )
    assert report.status == "DONE"
    assert json.loads(report.source_item_ids) == [7]
    assert json.loads(report.top_picks)[0]["source_title"] == material()["title"]


@pytest.mark.parametrize("index", [None, True, 1.0, "1", 0, -1])
def test_daily_report_quality_explicit_invalid_index_cannot_use_legacy_title_fallback(index):
    item = material()
    assert _match_picks_to_curated([{"source_idx": index, "source_title": item["title"]}], [item]) == ([], [])


@pytest.mark.parametrize("field", ["source_title", "source_url"])
def test_daily_report_quality_legacy_identity_must_be_unique_before_dictionary_deduplication(field):
    first = material(id=1)
    second = material(id=2, title=first["title"] if field == "source_title" else "另一条素材")
    pick = {field: first["title"] if field == "source_title" else first["url"], "reason": "讨论应用审核范围。"}
    assert _match_picks_to_curated([pick], [first, second]) == ([], [])


def test_daily_report_quality_trend_and_platform_fields_are_typed_public_text():
    from app.services.daily_report_editorial import review_daily_sections

    fallback = build_daily_editorial_fallback([material()], label="日报")
    result, issues = review_daily_sections(
        {
            "overview": "讨论应用审核。",
            "takeaway": "应用审核",
            "platform_tips": {"结合#10": ["写作建议"]},
            "trends": [{"title": "观察", "desc": {}}, {"title": "应用审核", "desc": "只代表本期素材", "color": []}],
        },
        fallback,
        "",
    )
    assert issues
    assert result["platform_tips"] == {}
    assert result["trends"] == [{"title": "应用审核", "desc": "只代表本期素材", "momentum": "stable"}]


@pytest.mark.asyncio
async def test_daily_report_quality_public_context_can_reference_real_background_issue(
    monkeypatch, test_session_factory
):
    report = await _generate_replay(
        monkeypatch,
        test_session_factory,
        {
            "overview": "GitHub issue #119记录了接口迁移问题。",
            "takeaway": "应用审核",
            "top_picks": [{"source_idx": 1, "reason": "对照应用审核的验证范围。"}],
        },
        background=[material(id=8, title="GitHub issue #119记录接口迁移问题")],
    )
    assert report.status == "DONE"
    assert report.overview == "GitHub issue #119记录了接口迁移问题。"
