"""敏感词检测的 category / severity 常量（跨层共享的纯常量放 core）。

词库数据文件与本模块同目录（JSON 无注释语法，来源与 License 记录在
每个文件的 `_meta` 字段）；更新口径见
.agents/notes/implemented/feature/2026-10-31-sensitive-word-check.md。
"""

from __future__ import annotations

# 命中分类：三类词库各一个 category，与同目录 JSON 文件一一对应
CATEGORY_ADVERTISING_EXTREME = "advertising_extreme"
CATEGORY_POLITICAL_ADULT = "political_adult"
CATEGORY_PLATFORM_THROTTLE = "platform_throttle"

# 严重度：high > medium > low，前端配色与排序共用同一口径
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_LOW = "low"

SEVERITIES: tuple[str, ...] = (SEVERITY_HIGH, SEVERITY_MEDIUM, SEVERITY_LOW)
CATEGORIES: tuple[str, ...] = (
    CATEGORY_ADVERTISING_EXTREME,
    CATEGORY_POLITICAL_ADULT,
    CATEGORY_PLATFORM_THROTTLE,
)
