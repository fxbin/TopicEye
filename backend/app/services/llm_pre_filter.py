"""
LLM 之前的规则过滤层（参照 content-signal-radar 设计）。

调用方在 ingest pipeline 写 content_items 之后、claim_pending 之前调
`apply_pre_filter(content)`：函数返回 (skip, reason)，
- skip=True: 内容已标 skip_analysis + skip_reason（不送 LLM 队列）
- skip=False: 正常进 LLM 队列

设计原则（参照 signal-radar 的 lowSignalPenalty + needsReview）：
- 硬低信号：明显是"GM/🎉/milestone"等噪音 → 100% 跳过
- 软低信号：自吹自擂（无技术细节） → 跳过
- 短内容：< 30 字符，无关键词 → 跳过
- 重复内容：title + url 与最近 7 天内已分析的相同 → 跳过

后续可加 needsReview（半 LLM 化）作为 PromptContext 传给 LLM。
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from app.models.content import ContentItem

logger = logging.getLogger(__name__)


# 硬低信号模式（直接跳过 LLM）
# 参照 signal-radar HARD_LOW_SIGNAL 列表
_HARD_LOW_SIGNAL_PATTERNS = [
    re.compile(r"congratulat", re.IGNORECASE),
    re.compile(r"happy birthday", re.IGNORECASE),
    re.compile(r"merry christmas", re.IGNORECASE),
    re.compile(r"happy (new year|friday|holidays|thanksgiving)", re.IGNORECASE),
    re.compile(r"happy friday", re.IGNORECASE),
    re.compile(r"good (morning|night|evening|afternoon)", re.IGNORECASE),
    re.compile(r"^\s*gm\b", re.IGNORECASE),  # 句子以 "GM" 开头
    re.compile(r"\bjust (hit|reached|gained)\s+\d+", re.IGNORECASE),  # "just hit 1000"
    re.compile(r"\b\d+k?\s*(followers?|subscribers?)\b", re.IGNORECASE),
    re.compile(r"follow(ers)?\s+milestone", re.IGNORECASE),
    re.compile(r"^\s*🚀+\s*$", re.IGNORECASE),  # 纯 emoji 内容
    re.compile(r"^[\s\U0001F300-\U0001FAFF]+$", re.IGNORECASE),  # 纯 emoji
]

# 软低信号：自吹自擂但无技术细节
_SOFT_LOW_SIGNAL_PATTERNS = [
    re.compile(r"\bmy new\b", re.IGNORECASE),
    re.compile(r"\bi just (launched|shipped|released|built)\b", re.IGNORECASE),
    re.compile(r"\bexcited to (announce|share|introduce)\b", re.IGNORECASE),
    re.compile(r"\bthrilled to\b", re.IGNORECASE),
]

_TECH_KEYWORDS = re.compile(
    r"\b(api|sdk|cli|architecture|benchmark|algorithm|model|llm|gpt|claude|"
    r"agent|workflow|automation|pipeline|framework|library|tool|integration|"
    r"performance|optimization|debugging|architecture|distributed|"
    r"database|sql|api|docker|kubernetes)\b",
    re.IGNORECASE,
)


def _is_hard_low_signal(text: str) -> bool:
    """返回 True 如果是硬低信号（明显的噪音模板）。"""
    if not text:
        return True
    return any(p.search(text) for p in _HARD_LOW_SIGNAL_PATTERNS)


def _is_soft_low_signal(text: str) -> bool:
    """软低信号：自吹自擂 + 无技术细节。"""
    if not text:
        return False
    if not any(p.search(text) for p in _SOFT_LOW_SIGNAL_PATTERNS):
        return False
    # 自吹自擂 + 无技术细节 → 软低信号
    return not _TECH_KEYWORDS.search(text)


def _is_too_short(text: str, min_chars: int = 30) -> bool:
    """内容过短（< 30 字符）大概率无信息量。"""
    return len((text or "").strip()) < min_chars


def should_skip_analysis(content: ContentItem) -> tuple[bool, Optional[str]]:
    """判断 content 是否应跳过 LLM 分析。

    Returns:
        (skip, reason): skip=True 时 reason 非空（hard_low_signal/short_text/self_promo/no_text）
    """
    # 拼接 title + summary + raw_content 作为判定文本
    parts = [content.title or "", content.summary or "", content.raw_content or ""]
    text = " ".join(parts).strip()

    if not text:
        return True, "no_text"

    if _is_hard_low_signal(text):
        return True, "hard_low_signal"

    if _is_soft_low_signal(text):
        return True, "self_promo"

    if _is_too_short(text):
        return True, "short_text"

    return False, None


# ── Cumulative counter（cumulative since startup） ──
_skip_count: int = 0


def get_skip_count() -> int:
    return _skip_count


def apply_pre_filter(content: ContentItem) -> bool:
    """应用 pre-filter 并就地更新 content.skip_analysis + skip_reason。

    Returns:
        True if content was marked skip_analysis=True.
    """
    global _skip_count
    skip, reason = should_skip_analysis(content)
    if skip:
        content.skip_analysis = True
        content.skip_reason = reason
        _skip_count += 1
        logger.debug(
            "LLM pre-filter: skipping content id=%d (%s)", content.id, reason,
        )
    return skip
