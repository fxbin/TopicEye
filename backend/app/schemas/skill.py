"""Skill read-API schemas.

These models back the ``/api/v1/skill/*`` read endpoints that external agents
(ZCode / Claude skills, n8n, custom scripts) consume. They mirror the existing
today-picks / trends payload shapes so the OpenAPI spec stays self-documenting
for agents that introspect ``/openapi.json``.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillTodayPicksResponse(BaseModel):
    """Today-picks payload for the skill read API.

    Identical shape to ``GET /contents/today-picks`` — a list of curated
    content cards plus visibility metadata. Each ``items[*].analysis`` carries
    ``adjusted_curation_score`` (final ranking score) and ``score_breakdown``.
    """

    items: list[dict[str, Any]] = Field(default_factory=list, description="精选内容卡片列表")
    total: int = Field(0, description="精选总数（去重后）")
    duplicates_hidden: int = Field(0, description="被去重剔除的重复条数")
    topics: list[dict[str, Any]] = Field(default_factory=list, description="关联话题分组")
    page: int = Field(1, description="页码（恒为 1）")
    page_size: int = Field(0, description="本页条数")


class SkillTrendsResponse(BaseModel):
    """Merged trends payload for the skill read API.

    Combines topic trends (``/trends/topics``) and keyword cloud
    (``/trends/keywords``) into one response so an agent fetches both in a
    single round-trip.
    """

    days: int = Field(..., description="回看天数")
    topics: list[dict[str, Any]] = Field(default_factory=list, description="话题趋势（按热度排序）")
    keywords: list[dict[str, Any]] = Field(default_factory=list, description="关键词词频（词云用）")
