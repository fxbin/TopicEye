from datetime import date, timedelta

import pytest

from app.services import digest_context
from app.services.scoring_engine import ScoringInput, score_items


class FailingDb:
    async def execute(self, *args, **kwargs):
        raise AssertionError("digest context should not query SQLAlchemy for analytical reads")


@pytest.mark.asyncio
async def test_fetch_analyzed_content_uses_duckdb_candidates_and_unified_scorer(monkeypatch):
    expected = [
        {
            "id": 1,
            "title": "DuckDB 摘要上下文样本",
            "category": "AI",
            "source_name": "测试信源",
            "crawled_at": "2026-06-06T00:00:00",
            "creator_score": 80,
            "viral_score": 70,
            "quality_score": 75,
            "info_density": 78,
            "actionability": 76,
            "source_weight": 70,
            "freshness_score": 85,
            "risk_score": 10,
            "curation_score": 82,
            "source_weight_db": 3,
            "feedback_score": 20,
        },
        {
            "id": 2,
            "title": "旧口径预筛高分但低质量",
            "category": "AI",
            "source_name": "测试信源",
            "crawled_at": "2026-06-06T00:00:00",
            "creator_score": 30,
            "viral_score": 30,
            "quality_score": 30,
            "info_density": 30,
            "actionability": 30,
            "source_weight": 50,
            "freshness_score": 40,
            "risk_score": 10,
            "curation_score": 70,
            "source_weight_db": 3,
            "feedback_score": 0,
        },
    ]
    calls = []

    def fake_query_content_for_weekly(start_date: str, end_date: str):
        calls.append((start_date, end_date))
        return expected

    monkeypatch.setattr(digest_context, "query_content_for_weekly", fake_query_content_for_weekly)

    result = await digest_context.fetch_analyzed_content(FailingDb(), "2026-06-01", "2026-06-07")
    expected_breakdown = score_items(
        [
            ScoringInput(
                content_id=1,
                title="DuckDB 摘要上下文样本",
                category="AI",
                source_name="测试信源",
                crawled_at="2026-06-06T00:00:00",
                curation_score=82,
                info_density=78,
                actionability=76,
                source_weight=70,
                creator_score=80,
                viral_score=70,
                freshness_score=85,
                quality_score=75,
                risk_score=10,
                source_weight_db=3,
                feedback_score=20,
            )
        ]
    )[0][0].to_dict()

    assert [row["id"] for row in result] == [1]
    assert result[0]["adjusted_score"] == expected_breakdown["final_score"]
    assert result[0]["score_breakdown"]["final_score"] == expected_breakdown["final_score"]
    assert result[0]["score_breakdown"]["dimension_scores"]["feedback_adjustment"] == 3.0
    assert calls == [("2026-06-01", "2026-06-07")]


@pytest.mark.asyncio
async def test_fetch_analyzed_content_propagates_duckdb_errors(monkeypatch):
    def fail_query_content_for_weekly(start_date: str, end_date: str):
        raise RuntimeError("duckdb unavailable")

    monkeypatch.setattr(digest_context, "query_content_for_weekly", fail_query_content_for_weekly)

    with pytest.raises(RuntimeError, match="duckdb unavailable"):
        await digest_context.fetch_analyzed_content(FailingDb(), "2026-06-01", "2026-06-07")


@pytest.mark.asyncio
async def test_fetch_analyzed_content_expands_window_without_db_fallback(monkeypatch):
    calls = []
    end_date = date(2026, 6, 30)
    expanded_start = (end_date - timedelta(days=29)).isoformat()
    expected = [
        {
            "id": 2,
            "title": "扩展窗口样本",
            "category": "产品",
            "source_name": "测试信源",
            "crawled_at": "2026-06-29T00:00:00",
            "creator_score": 82,
            "viral_score": 78,
            "quality_score": 84,
            "info_density": 82,
            "actionability": 80,
            "source_weight": 70,
            "freshness_score": 88,
            "risk_score": 12,
            "curation_score": 86,
            "source_weight_db": 3,
        }
    ]

    def fake_query_content_for_weekly(start_date: str, end_date: str):
        calls.append((start_date, end_date))
        return [] if len(calls) == 1 else expected

    monkeypatch.setattr(digest_context, "query_content_for_weekly", fake_query_content_for_weekly)

    result = await digest_context.fetch_analyzed_content_with_expanded_window(
        FailingDb(),
        "2026-06-01",
        "2026-06-30",
        expanded_days=30,
    )

    assert [row["id"] for row in result] == [2]
    assert result[0]["score_breakdown"]["selected"] is True
    assert calls == [
        ("2026-06-01", "2026-06-30"),
        (expanded_start, "2026-06-30"),
    ]


def test_build_items_text_prefers_adjusted_score_for_digest_prompt():
    text = digest_context.build_items_text(
        [
            {
                "title": "反馈提升后的选题",
                "category": "AI",
                "source_name": "测试信源",
                "curation_score": 70,
                "adjusted_score": 73,
                "creator_score": 68,
                "viral_score": 66,
                "quality_score": 72,
                "risk_score": 10,
            }
        ]
    )

    assert "精选:73" in text


def test_digest_row_to_scoring_input_preserves_full_duckdb_signals():
    scoring_input = digest_context._row_to_scoring_input(
        {
            "id": 7,
            "title": "完整 DuckDB scorer 输入",
            "category": "AI",
            "source_name": "权重信源",
            "crawled_at": "2026-06-06T00:00:00",
            "curation_score": 82,
            "info_density": 79,
            "actionability": 77,
            "source_weight": 71,
            "creator_score": 80,
            "viral_score": 70,
            "freshness_score": 88,
            "quality_score": 76,
            "hot_score": 69,
            "risk_score": 12,
            "source_weight_db": 5,
            "feedback_score": 20,
        }
    )

    assert scoring_input.content_id == 7
    assert scoring_input.info_density == 79
    assert scoring_input.actionability == 77
    assert scoring_input.source_weight == 71
    assert scoring_input.freshness_score == 88
    assert scoring_input.hot_score == 69
    assert scoring_input.source_weight_db == 5
    assert scoring_input.feedback_score == 20
