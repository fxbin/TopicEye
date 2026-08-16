from datetime import UTC, datetime, timedelta

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
            published_at=datetime.now(UTC) - timedelta(days=5),
            crawled_at=datetime.now(UTC) - timedelta(days=5),
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


# ── P1 修复回归: falsy-zero + quality_factor 去重 ──────────────────

from app.services.scoring_engine import (  # noqa: E402 — 该组回归用例就近导入内部符号
    _compute_base_score,
    _compute_quality_factor,
    _dim,
)


def test_dim_none_uses_default():
    assert _dim(None) == 50.0
    assert _dim(None, default=0.0) == 0.0


def test_dim_zero_preserved():
    """核心修复: 0 是合法低分, 不应被当成缺失（修复前 `0 or 50` → 50）。"""
    assert _dim(0) == 0.0
    assert _dim(0.0) == 0.0


def test_dim_invalid_returns_default():
    assert _dim("not-a-number") == 50.0
    assert _dim(float("nan")) == 50.0


def test_zero_info_density_scores_lower_than_missing():
    """info_density=0 (该淘汰) 的 base 应低于 None(中性 50)。"""
    item_zero = _item(1, info_density=0, curation_score=0)  # 走 fallback 路径
    item_missing = _item(2, info_density=None, curation_score=None)
    base_zero, _ = _compute_base_score(item_zero)
    base_missing, _ = _compute_base_score(item_missing)
    assert base_zero < base_missing


def test_quality_factor_uses_quality_score_not_dims():
    """quality_factor 只用 quality_score, 高质量分→factor=1.0 即使 info_density 低。"""
    item = _item(1, info_density=20, quality_score=85)
    factor, _ = _compute_quality_factor(item)
    assert factor == 1.0


def test_quality_factor_low_quality_penalized():
    """quality_score 低触发惩罚, 不受 info_density 高低影响。"""
    item = _item(1, info_density=80, quality_score=30)
    factor, _ = _compute_quality_factor(item)
    assert factor < 0.7


def test_time_decay_bad_timestamp_does_not_crash():
    """格式错误的 timestamp 不应让评分崩溃。"""
    from app.services.scoring_engine import _compute_time_decay

    item = _item(1, published_at="not-a-date")
    decay = _compute_time_decay(item)
    assert 0.0 < decay <= 1.0
