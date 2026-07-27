from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AiAnalysis(Base):
    __tablename__ = "ai_analyses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    content_id: Mapped[int] = mapped_column(Integer, ForeignKey("content_items.id", ondelete="CASCADE"), nullable=False)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    hot_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    freshness_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    creator_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    viral_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    risk_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    platform_fit: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    recommended_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_points: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    audience_emotion: Mapped[str | None] = mapped_column(Text, nullable=True)
    creator_angles: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    title_suggestions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    outline_suggestions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    xiaohongshu_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    short_video_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    risk_notes: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # ── Curation fields ──
    curation_score: Mapped[float | None] = mapped_column(Float, nullable=True, default=0.0)
    tags: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # multi-tag: ["模型","产品"]
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)  # AI 生成口语化推荐理由
    source_weight: Mapped[float | None] = mapped_column(Float, nullable=True, default=50.0)
    info_density: Mapped[float | None] = mapped_column(Float, nullable=True, default=50.0)
    actionability: Mapped[float | None] = mapped_column(Float, nullable=True, default=50.0)
    # ── Model cascade routing metadata ──
    analysis_mode: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="pro_only"
    )  # pro_only|lite_only|cascade
    prescreen_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    escalated: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=False)
    escalation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    prescreen_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    prescreen_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    # ── Round-2 enrichment fields ──
    enrichment_status: Mapped[str | None] = mapped_column(
        Text, nullable=True, default="pending"
    )  # pending|completed|error
    enrichment: Mapped[dict | None] = mapped_column(
        JSON, nullable=True
    )  # background/related_angles/why_matters/creator_tips
    # ── Summary provenance ──
    # llm_pro = Pro 模型直接生成（pro_only / cascade 中 escalated）
    # llm_lite = Lite 模型生成（cascade 模式 lite_only 命中）
    # local_fallback = LLM 失败后本地兜底（_local_analysis_result）
    summary_source: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )

    content: Mapped[ContentItem] = relationship(back_populates="analyses")
