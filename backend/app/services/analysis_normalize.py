"""
分析结果规范化纯函数簇。

仅依赖 Python 内置(Any、json)，可独立单元测试。
从 app.services.analysis 拆出，外部使用方保持从 analysis 模块 import 即可。

包含:
- _detect_lang                内容语言检测(中英)
- _valid_analysis_result      分析结果最小有效契约校验
- _normalize_deep_read        论文精读判定(score/worth 调和)
- _clamp_score                0-100 数值钳位
- _normalize_text             字符串清洗 + 长度截断
- _parse_json_list            JSON 数组字符串解析
- _normalize_string_list      字符串列表去重/截断
- _normalize_analysis_result  完整分析结果规范化
"""

from __future__ import annotations

import json
from typing import Any


def _detect_lang(title: str, content: str) -> str:
    """Detect whether content is primarily Chinese or English.

    Uses character-range heuristics: CJK range vs Latin ASCII letters.
    Returns 'en' if ASCII letters dominate the sample, else 'zh'.
    """
    sample = (title + " " + content)[:500]
    ascii_letters = sum(1 for c in sample if c.isascii() and c.isalpha())
    cjk_chars = sum(1 for c in sample if "\u4e00" <= c <= "\u9fff")
    # If we have meaningful CJK content, prefer Chinese
    if cjk_chars >= 10:
        return "zh"
    if ascii_letters >= 20 and ascii_letters / max(ascii_letters + cjk_chars, 1) > 0.6:
        return "en"
    return "zh"


def _valid_analysis_result(result: Any) -> bool:
    """Return whether the model result contains the minimum analysis contract.

    收紧校验：不仅要求 scores/curation 是 dict，还要求 scores 含至少一个
    有效数值、summary 非空。否则 LLM 返回空壳（如 {"scores":{},"summary":""}）
    会被当成有效分析，垃圾数据静默入库污染精选评分。
    """
    if not isinstance(result, dict):
        return False
    scores = result.get("scores")
    curation = result.get("curation")
    if not isinstance(scores, dict) or not isinstance(curation, dict):
        return False
    # scores 至少含一个 0-100 的有效数值
    has_valid_score = any(
        isinstance(v, (int, float)) and 0 <= v <= 100 for v in scores.values()
    )
    if not has_valid_score:
        return False
    # summary 非空（LLM 必须给出实际摘要）
    summary = result.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    return True


def _normalize_deep_read(raw: Any) -> dict[str, Any] | None:
    """归一化论文精读判定：调和 worth_deep_read 与 deep_read_score 的矛盾。

    prompt 约定 deep_read_score≥70 → worth_deep_read=true。若 LLM 输出矛盾
    (如 score=85 但 worth=false)，以 score 为准重新派生 worth。
    同时处理 worth_deep_read 为字符串 "false" 的 bool 解析 bug。
    """
    if not isinstance(raw, dict):
        return None
    # deep_read_score 数值化 + clamp
    try:
        score = max(0, min(100, float(raw.get("deep_read_score", 0))))
    except (TypeError, ValueError):
        score = 0.0
    # worth_deep_read 显式 bool 解析（bool("false") 是 True 的陷阱）
    raw_worth = raw.get("worth_deep_read", False)
    if isinstance(raw_worth, bool):
        worth = raw_worth
    else:
        worth = str(raw_worth).strip().lower() in ("true", "1", "yes")
    # 调和矛盾：以 score≥70 为准（prompt 约定）
    worth = worth or score >= 70
    return {
        "worth_deep_read": worth,
        "deep_read_score": round(score, 1),
        "deep_read_reason": str(raw.get("deep_read_reason") or "")[:200],
    }


def _clamp_score(value: Any, default: float = 50) -> float:
    try:
        return max(0, min(100, float(value)))
    except (TypeError, ValueError):
        return default


def _normalize_text(value: Any, *, default: str = "", max_length: int = 600) -> str:
    if not isinstance(value, str):
        return default

    text = value.strip()
    if not text:
        return default
    return text[:max_length]


def _parse_json_list(value: str) -> list[Any] | None:
    text = value.strip()
    if not text.startswith("["):
        return None
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def _normalize_string_list(
    value: Any,
    *,
    max_items: int = 8,
    max_length: int = 120,
) -> list[str]:
    if isinstance(value, str):
        parsed = _parse_json_list(value)
        candidates: Any = parsed if parsed is not None else [value]
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, str):
            continue
        text = item.strip()[:max_length]
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
        if len(normalized) >= max_items:
            break

    return normalized


def _normalize_analysis_result(result: dict[str, Any]) -> dict[str, Any]:
    scores = result.get("scores", {})
    normalized_scores = {
        key: _clamp_score(scores.get(key), 50)
        for key in ["quality_score", "hot_score", "freshness_score", "creator_score", "viral_score", "risk_score"]
    }

    curation = result.get("curation", {})
    normalized_curation = {
        "curation_score": _clamp_score(curation.get("curation_score"), 0),
        "info_density": _clamp_score(curation.get("info_density"), 50),
        "actionability": _clamp_score(curation.get("actionability"), 50),
        "source_weight": _clamp_score(curation.get("source_weight"), 50),
    }

    return {
        **result,
        "summary": _normalize_text(result.get("summary"), max_length=600),
        "key_points": _normalize_string_list(result.get("key_points"), max_items=8, max_length=240),
        "recommendation": _normalize_text(result.get("recommendation"), max_length=800),
        "creator_angles": _normalize_string_list(result.get("creator_angles"), max_items=8, max_length=240),
        "title_suggestions": _normalize_string_list(result.get("title_suggestions"), max_items=6, max_length=80),
        "risk_notes": _normalize_text(result.get("risk_notes"), max_length=500),
        "tags": _normalize_string_list(result.get("tags"), max_items=8, max_length=40),
        "scores": normalized_scores,
        "curation": normalized_curation,
    }