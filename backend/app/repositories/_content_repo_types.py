"""Content repository types (dataclasses & constants).

从 app.repositories.content_repo 抽出的纯数据容器，便于：
- 在 scoring_flow 等其他模块单独引用，避免引入 ContentRepo 整个仓库
- 减少 content_repo.py 体积（它本身已 750+ 行）
- dataclass 单测

包含：
- ANALYSIS_STALE_MINUTES  — 分析声明超时阈值
- ScoringContentRow         — scoring 专用轻量级 row dataclass（30+ 字段）
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

ANALYSIS_STALE_MINUTES = 10


@dataclass
class ScoringContentRow:
    """Lightweight content + latest analysis row for scoring diagnostics."""

    id: int
    title: str
    url: str
    source_id: int | None
    source_name: str | None
    category: str | None
    summary: str | None
    tags: Any | None
    is_favorited: bool
    published_at: datetime | None
    crawled_at: datetime
    source_weight_db: int
    ai_summary: str | None
    recommendation: str | None
    recommended_reason: str | None
    analysis_tags: Any | None
    creator_angles: Any | None
    curation_score: float | None
    info_density: float | None
    actionability: float | None
    source_weight: float | None
    creator_score: float | None
    viral_score: float | None
    freshness_score: float | None
    quality_score: float | None
    hot_score: float | None
    risk_score: float | None