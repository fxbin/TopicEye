"""排序效果基准快照。

按时间窗物化一次评测结果（top-N 值得写比例、重复事件率、来源覆盖率、
采用率 + 当时的评分配置快照）。配置快照是关键：后续调整权重/门槛时，
前后数字对比才有可解释性——知道每个数字是在哪套参数下测出来的。

surface 标识被测面（当前为 today_picks_v1：非个性化的当日精选基础排序）。
"""

from __future__ import annotations

import enum
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class EvalSurface(enum.StrEnum):
    TODAY_PICKS_V1 = "today_picks_v1"


class RankingEvalSnapshot(Base):
    __tablename__ = "ranking_eval_snapshots"
    __table_args__ = (UniqueConstraint("surface", "window_start", name="uq_eval_surface_window"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    surface: Mapped[str] = mapped_column(String(50), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # 指标集合：top10_worth_ratio / top10_duplicate_event_rate / top10_source_coverage /
    # top10_adoption_rate 等（结构见 services/ranking_eval.py）
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # 该次评测时的评分配置快照（scoring_engine.CONFIG 摘要）
    scoring_config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # top-N 明细（id/标题/得分/标注/等级），便于人工复核
    item_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
