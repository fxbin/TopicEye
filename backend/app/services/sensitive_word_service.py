"""文稿敏感词扫描（违禁词 / 广告法极限词 / 平台限流词）。

纯函数扫描链路：无 DB、无外部依赖，词库是包内静态 JSON
（`app/core/sensitive_words/`，来源与 License 记录在各自 `_meta` 字段）。

匹配与偏移口径（与 owning note 一致，改动前先读）：

- **偏移是原文字符偏移**（Python codepoint 坐标，前端用按 codepoint 切分对齐，
  避免 UTF-16 代理对错位）；**不做 NFKC 归一**，否则偏移漂移、高亮错位。
- **全角/半角标点与空白视为分隔符**：扫描前把 `\\s\\W` 字符替换为 `\\x00`
  （1:1 替换，偏移不变），词条经校验不含分隔符，因此不可能产生跨标点命中。
- **不做全半角折叠、不承诺繁体**（`最ＮＯ.１`、繁体字形不在此列）。
- **同 start 保留最长词**：union 内按词长降序排列（Python re 的 alternation
  是分支左侧优先而非最长优先，顺序是实现的一部分）；跨类重叠区间贪心保留
  先出现者，完全同区间时按严重度 high>medium>low 决胜，再按 category 名稳定排序。
"""

from __future__ import annotations

import functools
import json
import logging
import re
from pathlib import Path
from typing import TypedDict

from app.core.sensitive_words import (
    CATEGORY_ADVERTISING_EXTREME,
    CATEGORY_PLATFORM_THROTTLE,
    CATEGORY_POLITICAL_ADULT,
    SEVERITIES,
    SEVERITY_HIGH,
    SEVERITY_LOW,
    SEVERITY_MEDIUM,
)

logger = logging.getLogger(__name__)

# 词库文件与 category 一一对应
_CATEGORY_FILES: dict[str, str] = {
    CATEGORY_ADVERTISING_EXTREME: "advertising_extreme.json",
    CATEGORY_POLITICAL_ADULT: "political_adult.json",
    CATEGORY_PLATFORM_THROTTLE: "platform_throttle.json",
}

# 严重度排序权重：同区间命中时高严重度优先
_SEVERITY_RANK: dict[str, int] = {SEVERITY_HIGH: 3, SEVERITY_MEDIUM: 2, SEVERITY_LOW: 1}

# 分隔符：空白 + 所有标点/符号（含全角）。词条不得包含这些字符。
_SEPARATOR_RE = re.compile(r"[\s\W]")

# 占位符：替换分隔符后词表正则不可能跨标点命中，且替换是 1:1 的、偏移不变
_PLACEHOLDER = "\x00"


class SensitiveWordHit(TypedDict):
    """一次命中：词条、分类、严重度、原文偏移与替换建议。"""

    word: str
    category: str
    severity: str
    start: int
    end: int
    suggestion: str | None


@functools.cache
def load_words(category: str) -> tuple[dict[str, str], ...]:
    """加载并校验某分类的词库（进程内缓存）。

    返回原始词条元组（含 word/severity/suggestion）。含分隔符、空词或
    非法 severity 的词条显式 warning 并跳过——静态数据文件出错不能安静失败，
    也不能拖垮接口；配套测试断言内置三份词库零跳过。
    """
    filename = _CATEGORY_FILES.get(category)
    if filename is None:
        raise ValueError(f"未知敏感词分类: {category}")
    path = Path(__file__).resolve().parent.parent / "core" / "sensitive_words" / filename
    data = json.loads(path.read_text(encoding="utf-8"))
    validated: list[dict[str, str]] = []
    for entry in data.get("words", []):
        word = str(entry.get("word", ""))
        severity = str(entry.get("severity", ""))
        if not word or _SEPARATOR_RE.search(word):
            logger.warning("敏感词库 %s 跳过含分隔符/空词条: %r", filename, entry)
            continue
        if severity not in SEVERITIES:
            logger.warning("敏感词库 %s 跳过非法 severity 词条: %r", filename, entry)
            continue
        validated.append(
            {
                "word": word,
                "severity": severity,
                "suggestion": entry.get("suggestion") or "",
            }
        )
    if not validated:
        raise ValueError(f"敏感词库 {filename} 为空或全部词条非法")
    return tuple(validated)


@functools.cache
def _compiled_patterns() -> dict[str, re.Pattern[str]]:
    """每类词库预编译一个 union 正则（按词长降序，实现「同 start 保留最长」）。"""
    patterns: dict[str, re.Pattern[str]] = {}
    for category in _CATEGORY_FILES:
        words = sorted((w["word"] for w in load_words(category)), key=len, reverse=True)
        union = "|".join(re.escape(w) for w in words)
        patterns[category] = re.compile(union)
    return patterns


def scan(text: str) -> list[SensitiveWordHit]:
    """扫描文稿，返回命中清单（按 start 升序；重叠区间贪心保留最长/先出现）。

    纯函数：同一输入恒得同一输出；空串/无命中返回空列表。
    """
    if not text:
        return []

    # 分隔符 1:1 替换为占位符：不可能跨标点命中，偏移与原文严格一致
    masked = _SEPARATOR_RE.sub(_PLACEHOLDER, text)

    raw: list[SensitiveWordHit] = []
    for category, pattern in _compiled_patterns().items():
        words_by_text = {w["word"]: w for w in load_words(category)}
        for m in pattern.finditer(masked):
            entry = words_by_text[m.group()]
            raw.append(
                SensitiveWordHit(
                    word=entry["word"],
                    category=category,
                    severity=entry["severity"],
                    start=m.start(),
                    end=m.end(),
                    suggestion=entry["suggestion"] or None,
                )
            )

    # start 升序、同 start 长词优先、同区间高严重度优先、category 名稳定排序
    raw.sort(key=lambda h: (h["start"], -(h["end"] - h["start"]), -_SEVERITY_RANK[h["severity"]], h["category"]))

    hits: list[SensitiveWordHit] = []
    last_end = 0
    for hit in raw:
        if hit["start"] >= last_end:
            hits.append(hit)
            last_end = hit["end"]
    return hits
