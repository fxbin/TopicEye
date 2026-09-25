"""行为标注推断（services/content_labeling.py）纯逻辑单测。"""

from __future__ import annotations

from app.services.content_labeling import (
    LABEL_NOT_WORTH,
    LABEL_WORTH,
    POSITIVE_THRESHOLD,
    SIGNAL_WEIGHTS,
    compute_label_from_signals,
)


def test_strong_adoption_alone_is_worth_writing():
    label, confidence, _ = compute_label_from_signals({"creation": 1})
    assert label == LABEL_WORTH
    assert confidence == 1.0  # 单个成稿即满置信


def test_moderate_positive_signals_accumulate():
    label, confidence, evidence = compute_label_from_signals({"favorite": 1, "like": 1})
    assert label == LABEL_WORTH  # 3 + 2 = 5 ≥ 3
    assert 0.5 < confidence < 1.0
    assert evidence == {"favorite": 1, "like": 1}


def test_single_weak_signal_is_insufficient():
    label, confidence, _ = compute_label_from_signals({"like": 1})
    assert label is None  # 2 < 3，宁缺毋滥
    assert confidence == 0.0


def test_negative_signals_dominate():
    label, confidence, _ = compute_label_from_signals({"dislike": 1})
    assert label == LABEL_NOT_WORTH
    assert confidence > 0.5


def test_mixed_signals_net_out():
    # 收藏(+3) + 跳过(-2) = +1 → 证据不足
    assert compute_label_from_signals({"favorite": 1, "skip": 1})[0] is None


def test_thresholds_match_weight_scale():
    # 阈值必须落在「单个中等信号」与「两个弱正信号」之间，避免过松过紧
    assert SIGNAL_WEIGHTS["like"] < POSITIVE_THRESHOLD < SIGNAL_WEIGHTS["favorite"] + SIGNAL_WEIGHTS["like"]


def test_unknown_signal_ignored():
    # like:1 = +2 不足阈值；未知信号不计分、不入证据
    label, _, evidence = compute_label_from_signals({"unknown_signal": 5, "like": 1})
    assert label is None
    assert "unknown_signal" not in evidence
