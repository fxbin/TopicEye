"""标签规范化 —— 键口径的单一事实源。

标签有三个消费方共用同一份规范化口径：
- 存储（content_items.tags / ai_analyses.tags）：写入时拆复合、统一键；
- 服务端标签筛选（GET /contents?tag=…）：参数与存储两侧同键比较；
- 兴趣向量：避免 ai/AI 这类大小写变体拆散同一兴趣的权重积累。

规则：
- 复合标签拆分：模型偶尔把 "AI安全, 联合国, 风险警告" 当成一个数组
  元素返回，按中英文逗号 / 分号 / 顿号拆开（不拆 / 和 |，避免误伤
  "BERT/NLP" 这类合法整段标签）。
- 键规范化：NFKC → 压缩内部空白 → 去首尾空白 → ASCII 小写（中文等
  无大小写的文字不受影响）。
- 展示形态由前端 prettifier 负责（src/lib/utils.ts prettyTag），存储
  只保存规范键。
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

_SPLIT_RE = re.compile(r"[,，、;；]")
_WS_RE = re.compile(r"\s+")


def normalize_tag_key(raw: str) -> str:
    """单个标签 → 规范化键。"""
    text = unicodedata.normalize("NFKC", str(raw))
    text = _WS_RE.sub(" ", text).strip()
    return text.lower()


def split_compound_tags(raw: str) -> list[str]:
    """拆分复合标签字符串，保留非空片段（已去空白，未做键规范化）。"""
    return [part.strip() for part in _SPLIT_RE.split(raw) if part.strip()]


def normalize_tag_list(value: Any, *, max_items: int = 8, max_length: int = 40) -> list[str]:
    """列表级规范化：拆复合 → 键规范化 → 去重保序 → 截断。

    兼容 list / JSON 字符串 / None 三种输入（历史数据 tags 列可能存过
    JSON 字符串）。
    """
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            parsed = None
        candidates: Any = parsed if isinstance(parsed, list) else [value]
    elif isinstance(value, list | tuple | set):
        candidates = value
    else:
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if not isinstance(item, str):
            continue
        for part in split_compound_tags(item):
            key = normalize_tag_key(part)[:max_length].strip()
            if not key or key in seen:
                continue
            normalized.append(key)
            seen.add(key)
            if len(normalized) >= max_items:
                return normalized
    return normalized
