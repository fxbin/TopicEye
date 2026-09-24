"""推荐等级判定（services/recommendation_level.py）单元测试。

用例与前端 src/lib/__tests__/recommendation.test.ts 对齐——两侧规则
和阈值必须同步演进（先后端持久化等级，前端本地规则作旧数据兜底）。
"""

from __future__ import annotations

from app.services.analysis_normalize import _normalize_analysis_result
from app.services.recommendation_level import (
    LEVEL_AVOID,
    LEVEL_DEEP_DIVE,
    LEVEL_HOT_RIDE,
    LEVEL_INSUFFICIENT,
    LEVEL_STRONG_WRITE,
    LEVEL_WATCH,
    classify_recommendation_level,
)


def _classify(
    quality=60,
    hot=60,
    freshness=60,
    creator=60,
    viral=60,
    risk=30,
    *,
    curation=0.0,
    text=True,
):
    return classify_recommendation_level(
        quality_score=quality,
        hot_score=hot,
        freshness_score=freshness,
        creator_score=creator,
        viral_score=viral,
        risk_score=risk,
        curation_score=curation,
        has_text_signal=text,
    )


def test_strong_write_when_creator_high_risk_low():
    assert _classify(creator=90, risk=20) == LEVEL_STRONG_WRITE


def test_hot_ride_when_hot_high_risk_mid():
    assert _classify(hot=85, risk=55) == LEVEL_HOT_RIDE
    # 低于观察线 75 仍可蹭热点；超过则不建议追
    assert _classify(hot=90, risk=70) == LEVEL_HOT_RIDE


def test_deep_dive_when_quality_high_freshness_low():
    assert _classify(quality=90, freshness=30) == LEVEL_DEEP_DIVE


def test_watch_when_creator_and_hot_at_threshold():
    assert _classify(creator=75, hot=75, risk=45) == LEVEL_WATCH


def test_quality_gate_before_positive_levels():
    # 报告复现：质量 10 + 创作价值 90 不得给正面推荐
    assert _classify(quality=10, creator=90, risk=20) == LEVEL_AVOID


def test_risk_hard_exclude_before_hot_ride():
    # 报告复现：热度 90 + 风险 95 不得判为蹭热点
    assert _classify(hot=90, risk=95) == LEVEL_AVOID


def test_low_creator_or_high_risk_avoided():
    assert _classify(creator=40) == LEVEL_AVOID
    assert _classify(risk=80) == LEVEL_AVOID


def test_default_profile_maps_to_insufficient():
    assert _classify(quality=50, hot=50, freshness=50, creator=50, viral=50, risk=50, text=False) == (
        LEVEL_INSUFFICIENT
    )
    # 有文本信号（+ 无正面分数）仍不足以离开信号不足档
    assert _classify(quality=50, hot=50, freshness=50, creator=50, viral=50, risk=50, text=True) == (LEVEL_INSUFFICIENT)


def test_none_scores_default_to_50():
    assert classify_recommendation_level(creator_score=90, risk_score=20) == LEVEL_STRONG_WRITE
    assert classify_recommendation_level(has_text_signal=True) == LEVEL_INSUFFICIENT


def test_fallback_insufficient():
    assert _classify(creator=55, hot=55, quality=55, risk=55) == LEVEL_INSUFFICIENT


def test_normalize_analysis_result_stamps_level_and_tags():
    result = _normalize_analysis_result(
        {
            "scores": {
                "quality_score": 60,
                "hot_score": 60,
                "freshness_score": 60,
                "creator_score": 90,
                "viral_score": 60,
                "risk_score": 20,
            },
            "curation": {"curation_score": 70, "info_density": 70, "actionability": 70, "source_weight": 60},
            "summary": "值得写的选题",
            "tags": ["AI安全, 联合国", "OpenAI"],
        }
    )
    assert result["recommend_level"] == LEVEL_STRONG_WRITE
    assert result["tags"] == ["ai安全", "联合国", "openai"]
