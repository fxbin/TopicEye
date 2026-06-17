"""
趋势雷达 scraper 注册表和基类。

比内容 scraper 更轻量：
- 不走 LLM
- 返回 TrendingEntry dict
- pipeline 只做批量替换存储
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# ── 类型别名 ──────────────────────────────────────────────────────
TrendingEntry = dict[str, Any]
# 必须包含: title, rank, hot_value
# 可选包含: url, hot_value_raw, trend, cover_url, extra

# ── Registry ──────────────────────────────────────────────────────
_TRENDING_REGISTRY: dict[str, type] = {}


def register_trending(source: str):
    """Decorator: register a trending scraper."""

    def _cls(cls):
        _TRENDING_REGISTRY[source] = cls
        return cls

    return _cls


def get_trending_cls(source: str) -> type | None:
    return _TRENDING_REGISTRY.get(source)


def get_all_trending_sources() -> list[str]:
    return list(_TRENDING_REGISTRY.keys())


# ── Base class ────────────────────────────────────────────────────
class BaseTrendingScraper(ABC):
    """榜单 scraper 基类。"""

    # 子类必须设置
    SOURCE: str = ""
    CATEGORY: str = ""  # TrendingCategory value

    @abstractmethod
    async def fetch(self, client: httpx.AsyncClient) -> list[TrendingEntry]:
        """
        抓取榜单，返回条目列表。
        每个条目:
          title: str       标题/关键词
          rank: int        排名
          url: str         链接
          hot_value: int   热度值（数字）
          hot_value_raw: str  原始热度文本
          trend: str       "up"/"down"/"new"/"stable"
          cover_url: str   封面图
          extra: dict      平台特有数据
        """
        ...


# ── Auto-import submodules ───────────────────────────────────────
from . import (  # noqa: E402, F401
    _weibo,
    _baidu,
    _bilibili,
    _ithome,
    _zhihu_trending,
    _toutiao,
    _hackernews,
    _douyin_trending,
    _juejin,
    _eastmoney,
    _hupu,
    _kr36,
    _douban,
    _v2ex,
    _github,
    _sspai,
    # 网文平台榜单（公开 API，无需登录）
    _heiyan,
    _ishugui,
    # 以下接口暂不可用，保留代码待修复
    # _tieba,
    # _netease,
    # _xueqiu,
    # _sohu,
)
