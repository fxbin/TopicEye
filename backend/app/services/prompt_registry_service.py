"""Prompt registry sync service.

Scans ``app.services.llm.prompts.*`` modules at startup and upserts
their content into the ``prompt_registry`` table. This is a one-way
sync: Python source is the truth, DB is the catalog.

Usage (called once at app startup):

    await sync_prompt_registry(db)
"""

from __future__ import annotations

import hashlib
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.prompt_registry import PromptRegistry

logger = logging.getLogger(__name__)

# ── Prompt catalog definition ───────────────────────────────────────
# Each entry: (name, scene, description, source_module, attribute_path)
# The sync service will import the module and read the attribute.

_PROMPT_CATALOG: list[dict[str, str]] = [
    {
        "name": "analysis_system",
        "scene": "analysis",
        "description": "内容分析系统提示词（中文）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "SYSTEM_PROMPT",
    },
    {
        "name": "analysis_prompt",
        "scene": "analysis",
        "description": "内容分析用户提示词（中文）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "ANALYSIS_PROMPT",
    },
    {
        "name": "analysis_system_en",
        "scene": "analysis",
        "description": "内容分析系统提示词（英文信源）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "SYSTEM_PROMPT_EN",
    },
    {
        "name": "analysis_prompt_en",
        "scene": "analysis",
        "description": "内容分析用户提示词（英文信源）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "ANALYSIS_PROMPT_EN",
    },
    {
        "name": "paper_analysis_system",
        "scene": "analysis",
        "description": "学术论文分析系统提示词",
        "module": "app.services.llm.prompts.analysis",
        "attr": "PAPER_SYSTEM_PROMPT",
    },
    {
        "name": "paper_analysis_prompt",
        "scene": "analysis",
        "description": "学术论文分析用户提示词",
        "module": "app.services.llm.prompts.analysis",
        "attr": "PAPER_ANALYSIS_PROMPT",
    },
    {
        "name": "classification_system",
        "scene": "classification",
        "description": "内容分类系统提示词",
        "module": "app.services.llm.prompts.classification",
        "attr": "SYSTEM_PROMPT",
    },
    {
        "name": "classification_prompt",
        "scene": "classification",
        "description": "内容分类用户提示词",
        "module": "app.services.llm.prompts.classification",
        "attr": "CLASSIFICATION_PROMPT",
    },
    {
        "name": "creation_explore",
        "scene": "creation_explore",
        "description": "探索模式-探索期提示词",
        "module": "app.services.llm.prompts.creation",
        "attr": "EXPLORE_PROMPT",
    },
    {
        "name": "creation_focus",
        "scene": "creation_focus",
        "description": "探索模式-聚焦期提示词",
        "module": "app.services.llm.prompts.creation",
        "attr": "FOCUS_PROMPT",
    },
    {
        "name": "creation_converge",
        "scene": "creation_converge",
        "description": "探索模式-收敛期提示词（含自评）",
        "module": "app.services.llm.prompts.creation",
        "attr": "CONVERGE_PROMPT",
    },
    {
        "name": "prescreen_system",
        "scene": "content_prescreen",
        "description": "内容预筛系统提示词（Lite cascade）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "PRESCREEN_SYSTEM_PROMPT",
    },
    {
        "name": "prescreen_prompt",
        "scene": "content_prescreen",
        "description": "内容预筛用户提示词（Lite cascade）",
        "module": "app.services.llm.prompts.analysis",
        "attr": "PRESCREEN_PROMPT",
    },
    {
        "name": "enrichment_system",
        "scene": "enrichment",
        "description": "内容Enrichment系统提示词",
        "module": "app.services.llm.prompts.enrichment",
        "attr": "SYSTEM_PROMPT",
    },
    {
        "name": "enrichment_prompt",
        "scene": "enrichment",
        "description": "内容Enrichment用户提示词",
        "module": "app.services.llm.prompts.enrichment",
        "attr": "ENRICHMENT_PROMPT",
    },
    {
        "name": "daily_report_system",
        "scene": "daily_report",
        "description": "日报系统提示词",
        "module": "app.services.llm.prompts.daily_report",
        "attr": "SYSTEM_PROMPT",
    },
    {
        "name": "daily_report_prompt",
        "scene": "daily_report",
        "description": "日报用户提示词",
        "module": "app.services.llm.prompts.daily_report",
        "attr": "REPORT_PROMPT",
    },
    {
        "name": "weekly_digest_prompt",
        "scene": "weekly_digest",
        "description": "周报提示词（统一模板，参数化生成）",
        "module": "app.services.llm.prompts.digest",
        "attr": "DIGEST_PROMPT",
    },
    {
        "name": "monthly_digest_prompt",
        "scene": "monthly_digest",
        "description": "月报提示词（统一模板，参数化生成）",
        "module": "app.services.llm.prompts.digest",
        "attr": "DIGEST_PROMPT",
    },
    {
        "name": "angle_recommend_system",
        "scene": "angle_recommend",
        "description": "角度推荐系统提示词",
        "module": "app.services.llm.prompts.angle_recommend",
        "attr": "SYSTEM_PROMPT",
    },
    {
        "name": "angle_recommend_user",
        "scene": "angle_recommend",
        "description": "角度推荐用户提示词",
        "module": "app.services.llm.prompts.angle_recommend",
        "attr": "USER_TEMPLATE",
    },
]


def _import_prompt_content(module_path: str, attr: str) -> str | None:
    """Import a module and return the string value of an attribute."""
    try:
        import importlib

        mod = importlib.import_module(module_path)
        val = getattr(mod, attr, None)
        if isinstance(val, str):
            return val
        return None
    except Exception:
        logger.warning("Failed to import prompt %s.%s", module_path, attr, exc_info=True)
        return None


async def sync_prompt_registry(db: AsyncSession) -> int:
    """Sync all registered prompts into the ``prompt_registry`` table.

    Returns the number of prompts synced.
    """
    synced = 0
    for entry in _PROMPT_CATALOG:
        content = _import_prompt_content(entry["module"], entry["attr"])
        if content is None:
            continue

        version_hash = hashlib.md5(content.encode()).hexdigest()
        preview = content[:500]

        # Check if existing record needs updating
        result = await db.execute(
            select(PromptRegistry).where(PromptRegistry.name == entry["name"])
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            if existing.version_hash != version_hash:
                existing.full_content = content
                existing.content_preview = preview
                existing.version_hash = version_hash
                existing.source_file = f"{entry['module']}:{entry['attr']}"
                synced += 1
        else:
            record = PromptRegistry(
                name=entry["name"],
                scene=entry["scene"],
                description=entry["description"],
                source_file=f"{entry['module']}:{entry['attr']}",
                content_preview=preview,
                full_content=content,
                version_hash=version_hash,
            )
            db.add(record)
            synced += 1

    if synced > 0:
        try:
            await db.flush()
        except Exception:
            logger.warning("Prompt registry sync flush failed (non-fatal)", exc_info=True)
            await db.rollback()

    logger.info("Prompt registry synced: %d prompts", synced)
    return synced
