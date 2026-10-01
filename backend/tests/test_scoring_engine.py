from datetime import UTC, datetime, timedelta

from app.services.scoring_engine import (
    CONFIG,
    ScoringInput,
    _compute_percentile_threshold,
    score_items,
)

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


def test_diversity_no_boundary_cliff_beyond_former_top_n():
    """回归：多样性惩罚不得只在初排前 N 条生效。

    旧实现对初排 51 名之后的同源内容不再计惩罚（系数恒为 1），重排后
    原 51–60 名会集体越过前面被惩罚的内容冲进最终第 2–11 名。
    贪心重排后，同源内容的惩罚随入选次序单调加深，最终顺序应与初排
    顺序一致，第 51 名不能再跳到第 2 名。
    """
    total = 60
    items = [
        _item(
            i,
            source_id=7,
            category="AI",
            # curation_score 递减 → 初排顺序 = id 顺序
            curation_score=90 - i,
            creator_score=90 - i,
            quality_score=80,
        )
        for i in range(1, total + 1)
    ]

    scored = score_items(items)
    final_ids = [item.content_id for _bd, item in scored]

    assert final_ids == list(range(1, total + 1)), "同源内容最终顺序应保持初排顺序，无断层跳位"
    by_id = {item.content_id: bd for bd, item in scored}
    assert by_id[1].diversity_factor == 1.0, "同源第一条免惩罚"
    assert by_id[51].diversity_factor < 1.0, "第 51 条也必须被同源惩罚覆盖（旧实现在此断档）"
    # 4 位小数舍入后深名次的系数都会到 0.0，用第 10 名对比保证单调性可观测
    assert by_id[10].diversity_factor > by_id[51].diversity_factor, "越靠后惩罚越深"


def test_diversity_promotes_other_source_over_same_source_run():
    """多样性行为保持：同源连发时，另一来源的相近内容应排到同源第二条之前。"""
    same_source = [_item(i, source_id=7, category="AI", curation_score=80, creator_score=80) for i in range(1, 4)]
    other_source = _item(99, source_id=8, category="AI", curation_score=78, creator_score=78)

    scored = score_items(same_source + [other_source])
    final_ids = [item.content_id for _bd, item in scored]

    # 第一名仍是分数最高的同源第一条；同源第二条因惩罚被其它来源反超
    assert final_ids[0] == 1
    assert final_ids.index(99) < final_ids.index(2)


def test_p70_threshold_excludes_local_fallback_fake_scores():
    """#90：local_fallback 的确定性假分不得污染 P70 门槛。

    三组对照（自证明区分度——守门断言保证若删掉排除逻辑本测试必红）：
    - real_only：3 条真实分（90/80/70），门槛 T1 只由真实分决定；
    - mixed：再混入 2 条假分（85/75，标记 local_fallback）——真实项门槛
      仍应为 T1（排除生效）；
    - full：同样的 2 条 85/75 但标记为真实分析——门槛 T2 应不同于 T1，
      证明该分数组合确实会移动门槛（若排除逻辑失效，mixed 会退化成
      full 的门槛，测试转红）。
    """

    def _scored(content_id: int, curation: int, **extra) -> ScoringInput:
        return _item(content_id, curation_score=curation, **extra)

    real_items = [_scored(1, 90), _scored(2, 80), _scored(3, 70)]
    fallback_items = [
        _scored(98, 85, summary_source="local_fallback"),
        _scored(99, 75, summary_source="local_fallback"),
    ]
    same_scores_as_real = [_scored(98, 85), _scored(99, 75)]  # 不带标记

    baseline = score_items(list(real_items))
    mixed = score_items(real_items + fallback_items)
    full = score_items(real_items + same_scores_as_real)

    t_baseline = {bd.threshold_used for bd, _ in baseline}
    t_mixed_real = {bd.threshold_used for bd, item in mixed if item.content_id in (1, 2, 3)}
    t_full = {bd.threshold_used for bd, _ in full}

    assert len(t_baseline) == 1 and len(t_full) == 1
    assert t_mixed_real == t_baseline, "混入 fallback 假分后真实项门槛不应改变"
    assert t_full != t_baseline, "守门断言：85/75 混入真实批应移动门槛——本断言失败说明对照构造失去区分度"

    # fallback 项自身仍参与判定与展示（不静默消失），且用同一门槛判定
    fallback_results = {item.content_id: bd for bd, item in mixed if item.content_id in (98, 99)}
    assert len(fallback_results) == 2
    assert {bd.threshold_used for bd in fallback_results.values()} == t_baseline


def test_all_fallback_batch_falls_back_to_full_scores():
    """全候选皆降级时，门槛仍由本批实际分数决定，不退回全局默认阈值。

    这个分支不是防御性冗余：真实分为空时若直接把空列表交给
    ``_compute_percentile_threshold``，它会返回 ``CONFIG["curation_threshold"]``
    （55），而降级内容的 final_score 普遍低于该值，结果是整批一条都选不出来。
    """
    fallback_items = [_item(i, summary_source="local_fallback", curation_score=62) for i in range(1, 5)]
    scored = score_items(fallback_items)
    assert len(scored) == 4

    thresholds = {bd.threshold_used for bd, _ in scored}
    assert len(thresholds) == 1
    threshold = thresholds.pop()

    own_scores = [bd.final_score for bd, _ in scored]
    assert threshold == _compute_percentile_threshold(own_scores, 70), "门槛应由本批实际分数决定"

    # 守门断言：门槛退回全局默认时本批会全部低于阈值、页面一条都不出。
    # 删掉 score_items 里的 `or [bd.final_score ...]` 回退分支，本测试必红。
    assert threshold != CONFIG["curation_threshold"]
    assert any(bd.selected for bd, _ in scored), "门槛来自本批分数时至少应选出一条"


def test_scoring_input_defaults_summary_source_none():
    """未传 summary_source 的旧构造路径默认 None（表示真实 LLM 分析）。"""
    item = _item(1)
    assert item.summary_source is None
