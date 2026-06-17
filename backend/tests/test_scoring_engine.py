from datetime import datetime, timedelta, timezone

from app.services.scoring_engine import CONFIG, ScoringInput, score_items


_NOW = datetime(2026, 1, 1, 12, 0, 0)


def _item(content_id: int, **overrides) -> ScoringInput:
    data = {
        "content_id": content_id,
        "title": f"item {content_id}",
        "category": "AI",
        "source_id": content_id,
        "source_name": f"source {content_id}",
        "published_at": _NOW - timedelta(hours=2),
        "crawled_at": _NOW - timedelta(hours=1),
        "curation_score": 75,
        "info_density": 75,
        "actionability": 75,
        "source_weight": 70,
        "creator_score": 75,
        "viral_score": 70,
        "freshness_score": 70,
        "quality_score": 75,
        "hot_score": 65,
        "risk_score": 20,
        "source_weight_db": 3,
    }
    data.update(overrides)
    return ScoringInput(**data)


def test_weak_batch_does_not_select_items_only_because_of_percentile():
    weak_items = [
        _item(
            i,
            curation_score=48,
            info_density=35,
            actionability=35,
            creator_score=35,
            viral_score=40,
            quality_score=35,
            source_weight=50,
        )
        for i in range(1, 6)
    ]

    scored = score_items(weak_items)

    assert all(not breakdown.selected for breakdown, _ in scored)


def test_stale_high_quality_batch_can_still_select_percentile_winners():
    stale_items = [
        _item(
            i,
            published_at=datetime.now(timezone.utc) - timedelta(days=5),
            crawled_at=datetime.now(timezone.utc) - timedelta(days=5),
            curation_score=86 + i,
            info_density=82,
            actionability=82,
            creator_score=82,
            viral_score=78,
            quality_score=84,
            freshness_score=40,
        )
        for i in range(1, 8)
    ]

    scored = score_items(stale_items)

    assert any(breakdown.selected for breakdown, _ in scored)


def test_mid_risk_item_is_penalized_without_being_hard_filtered():
    safe = _item(1, risk_score=20)
    risky = _item(2, risk_score=70)

    scored = score_items([safe, risky])
    by_id = {item.content_id: breakdown for breakdown, item in scored}

    assert by_id[2].risk_factor < by_id[1].risk_factor
    assert by_id[2].final_score < by_id[1].final_score


def test_source_and_category_diversity_reduce_repeated_items():
    items = [_item(i, source_id=1, category="AI", curation_score=85, creator_score=85) for i in range(1, 6)]

    scored = score_items(items)
    by_id = {item.content_id: breakdown for breakdown, item in scored}

    assert by_id[1].diversity_factor == 1.0
    assert by_id[4].diversity_factor < by_id[2].diversity_factor
    assert by_id[5].diversity_factor < by_id[4].diversity_factor


def test_feedback_signal_is_clamped_before_scoring_adjustment():
    baseline = _item(1, feedback_score=0)
    normal_positive = _item(2, feedback_score=20)
    extreme_positive = _item(3, feedback_score=999)

    scored = score_items([baseline, normal_positive, extreme_positive])
    by_id = {item.content_id: breakdown for breakdown, item in scored}

    expected_adjustment = CONFIG["feedback_score_max"] * CONFIG["w_feedback"]
    assert by_id[2].dimension_scores["feedback_adjustment"] == expected_adjustment
    assert by_id[3].dimension_scores["feedback_adjustment"] == expected_adjustment
    assert by_id[3].base_score == by_id[2].base_score
    assert by_id[3].base_score > by_id[1].base_score
