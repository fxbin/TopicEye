"""网文周报跨平台共享工具。

从 app.services.webnovel_report 抽出的 3 个纯函数 + 2 个配置常量：
- _PLATFORM_LABELS / _platform_label     平台 key → 中文显示名
- _TRENDING_CATEGORY_FIELDS              黑岩/点众 TrendingItem.extra 中分类字段名
- _PER_PLATFORM_QUOTA / _TOP_LIMIT       跨平台涨跌榜配额
- _safe_int                              安全整数转换（处理 "1.2万" 等）
- _movement_item                         构造统一的 WebnovelMovementItem dict

5 个平台的 fetcher 共用这些工具，提取后便于：
- 单独单测 _movement_item 跨平台字段统一性
- 减少 webnovel_report.py 体积（它 530 行主要来自 5 平台 fetcher 细节）
"""

from __future__ import annotations

from typing import Any

_PLATFORM_LABELS: dict[str, str] = {
    "fanqie": "番茄小说",
    "qimao": "七猫小说",
    "zhihu": "知乎盐选",
    "heiyan": "黑岩书城",
    "ishugui": "点众阅读",
}


def _platform_label(platform: str) -> str:
    return _PLATFORM_LABELS.get(platform, platform)


# 黑岩/点众的分类字段在 TrendingItem.extra 中的 key
_TRENDING_CATEGORY_FIELDS: dict[str, str] = {
    "heiyan": "sortName",
    "ishugui": "shelf",
}

# 每平台在跨平台涨跌榜中的配额上限（避免量纲碾压）
_PER_PLATFORM_QUOTA = 5
_TOP_LIMIT = 10


def _safe_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    text = str(value).replace(",", "").strip()
    try:
        return int(float(text))
    except ValueError:
        return 0


def _movement_item(
    *,
    platform: str,
    title: str,
    author: str | None,
    category: str | None,
    rank_type: str,
    position: int,
    change: int,
    url: str | None = None,
) -> dict:
    return {
        "platform": platform,
        "platform_label": _platform_label(platform),
        "title": title,
        "author": author or "",
        "category": category or "未分类",
        "rank_type": rank_type,
        "position": position,
        "change": change,
        "url": url,
    }
