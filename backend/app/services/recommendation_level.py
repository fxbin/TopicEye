"""推荐等级判定 —— 后端单一实现。

与前端 ``src/lib/recommendation.ts`` 的 ``explainRecommendation`` 保持
同一规则与阈值（先过统一风险/质量/创作价值门槛，再判断推荐类型）。
判定结果持久化到 ``ai_analyses.recommend_level``，供服务端筛选
（GET /contents?recommend_level=…）与 API 输出使用；前端函数继续作为
未回填旧数据的展示兜底。两侧阈值调整必须同步。

阈值锚点（与 scoring_engine.CONFIG 对齐）：
- RISK_HARD_EXCLUDE = risk_threshold（82）：后端精选流硬排除线；
- QUALITY_GATE_MIN = quality_gate_min（45）：内容过薄下限。
"""

from __future__ import annotations

LEVEL_STRONG_WRITE = "强烈建议写"
LEVEL_HOT_RIDE = "适合蹭热点"
LEVEL_DEEP_DIVE = "适合深挖"
LEVEL_WATCH = "值得观察"
LEVEL_AVOID = "不建议追"
LEVEL_INSUFFICIENT = "信号不足"

ALL_LEVELS: tuple[str, ...] = (
    LEVEL_STRONG_WRITE,
    LEVEL_WATCH,
    LEVEL_DEEP_DIVE,
    LEVEL_HOT_RIDE,
    LEVEL_AVOID,
    LEVEL_INSUFFICIENT,
)

RISK_HARD_EXCLUDE = 82.0
RISK_HIGH = 75.0
QUALITY_GATE_MIN = 45.0
_CREATOR_LOW = 50.0

_SCORE_KEYS = ("quality_score", "hot_score", "freshness_score", "creator_score", "viral_score", "risk_score")


def _num(value: float | None, default: float) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def classify_recommendation_level(
    *,
    quality_score: float | None = None,
    hot_score: float | None = None,
    freshness_score: float | None = None,
    creator_score: float | None = None,
    viral_score: float | None = None,
    risk_score: float | None = None,
    curation_score: float = 0.0,
    has_text_signal: bool = False,
) -> str:
    """按统一规则返回推荐等级。

    None 分数按写入路径的默认值 50 处理（legacy 行未回填的列），
    与「多维评分停留在默认 50」的信号不足判定口径一致。
    """
    scores = {
        "quality_score": _num(quality_score, 50.0),
        "hot_score": _num(hot_score, 50.0),
        "freshness_score": _num(freshness_score, 50.0),
        "creator_score": _num(creator_score, 50.0),
        "viral_score": _num(viral_score, 50.0),
        "risk_score": _num(risk_score, 50.0),
    }

    default_like = sum(1 for key in _SCORE_KEYS if scores[key] == 50.0)
    if default_like >= 5 and curation_score <= 0 and not has_text_signal:
        return LEVEL_INSUFFICIENT

    if scores["risk_score"] >= RISK_HARD_EXCLUDE:
        return LEVEL_AVOID
    if scores["creator_score"] < _CREATOR_LOW or scores["risk_score"] >= RISK_HIGH:
        return LEVEL_AVOID
    if scores["quality_score"] < QUALITY_GATE_MIN:
        return LEVEL_AVOID
    if scores["creator_score"] >= 85 and scores["risk_score"] <= 40:
        return LEVEL_STRONG_WRITE
    if scores["hot_score"] >= 80 and scores["risk_score"] > 40:
        return LEVEL_HOT_RIDE
    if scores["quality_score"] >= 85 and scores["freshness_score"] < 50:
        return LEVEL_DEEP_DIVE
    if scores["creator_score"] >= 70 and scores["hot_score"] >= 70 and scores["risk_score"] <= 60:
        return LEVEL_WATCH

    return LEVEL_INSUFFICIENT
