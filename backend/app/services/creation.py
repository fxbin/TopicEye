"""
Content creation assistant — generate platform-specific content plans.

Given a content item (already analyzed), produce a structured creation
blueprint for a specific platform (小红书/短视频/公众号).
"""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.analysis import AiAnalysis
from app.models.content import ContentItem
from app.repositories.analysis_queries import latest_analysis_id_subquery
from app.services.creation_explore import _attach_self_evaluation
from app.services.llm import call_llm_json  # noqa: E402
from app.services.llm.prompts.creation import PLATFORM_PROMPTS

logger = logging.getLogger(__name__)




def _normalize_string_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _validate_creation_plan(plan, platform: str) -> dict:
    if not isinstance(plan, dict):
        return {"error": "创作方案生成失败：模型返回格式不是 JSON 对象"}
    if plan.get("error"):
        return plan

    titles = _normalize_string_list(plan.get("titles"))
    if not titles:
        return {"error": "创作方案生成失败：模型未返回可用标题"}
    plan["titles"] = titles

    if platform == "xiaohongshu":
        structure = plan.get("structure")
        if not isinstance(structure, dict) or not _normalize_string_list(structure.get("points")):
            return {"error": "创作方案生成失败：小红书方案缺少正文结构"}
    elif platform == "short_video":
        scenes = plan.get("scenes")
        if not isinstance(scenes, list) or not scenes:
            return {"error": "创作方案生成失败：短视频方案缺少镜头脚本"}
    elif platform == "wechat":
        outline = plan.get("outline")
        if not isinstance(outline, list) or not outline:
            return {"error": "创作方案生成失败：公众号方案缺少文章大纲"}

    # Extract and validate self-evaluation (Sprint 3: 创作方案自评)
    plan = _attach_self_evaluation(plan)

    return plan


async def generate_creation_plan(
    db: AsyncSession,
    content_id: int,
    platform: str,
    user_id: int | None = None,
) -> dict:
    """
    Generate a platform-specific content creation plan for a content item.

    Returns the parsed plan dict from LLM.
    """
    # 1. Fetch content + analysis
    from sqlalchemy import select

    latest_analysis_id = latest_analysis_id_subquery(ContentItem, AiAnalysis)
    result = await db.execute(
        select(ContentItem, AiAnalysis)
        .join(AiAnalysis, AiAnalysis.id == latest_analysis_id)
        .where(ContentItem.id == content_id)
    )
    row = result.first()
    if not row:
        return {"error": "内容不存在或未分析"}

    content, analysis = row

    # 2. Build prompt
    platform_config = PLATFORM_PROMPTS.get(platform)
    if not platform_config:
        return {"error": f"不支持的平台: {platform}"}

    source_info = []
    if analysis.summary:
        source_info.append(f"摘要: {analysis.summary}")
    if analysis.key_points:
        source_info.append(f"核心观点: {'; '.join(analysis.key_points)}")
    if analysis.tags:
        tags = analysis.tags if isinstance(analysis.tags, list) else json.loads(analysis.tags or "[]")
        source_info.append(f"标签: {', '.join(tags)}")
    if analysis.creator_angles:
        source_info.append(f"创作角度: {'; '.join(analysis.creator_angles)}")
    if analysis.recommendation:
        source_info.append(f"推荐理由: {analysis.recommendation}")

    user_msg = f"""素材标题: {content.title}
素材来源: {content.source_name}

{chr(10).join(source_info)}

请基于以上素材，生成{platform_config["name"]}创作方案。"""

    messages = [
        {"role": "system", "content": platform_config["instruction"]},
        {"role": "user", "content": user_msg},
    ]

    # 3. Call LLM
    try:
        plan = await asyncio.wait_for(
            call_llm_json(messages, scene="creation_plan"),
            timeout=settings.CREATION_PLAN_TIMEOUT_SECONDS,
        )
        plan = _validate_creation_plan(plan, platform)
        is_success = isinstance(plan, dict) and "error" not in plan
        if is_success:
            plan["_meta"] = {
                "content_id": content_id,
                "platform": platform,
                "platform_name": platform_config["name"],
            }
        # 4. Persist plan history（成功 / 失败都写入，失败作为日志）
        await _persist_creation_plan(
            db,
            user_id=user_id,
            content_id=content_id,
            content_title=content.title,
            platform=platform,
            platform_name=platform_config["name"],
            plan=plan if is_success else {},
            error=plan.get("error") if not is_success else None,
        )
        return plan
    except TimeoutError:
        logger.warning(
            "Creation plan timed out for content %s after %ss",
            content_id,
            settings.CREATION_PLAN_TIMEOUT_SECONDS,
        )
        error = f"创作方案生成超时，请稍后重试或切换更快的模型（>{settings.CREATION_PLAN_TIMEOUT_SECONDS}s）"
        await _persist_creation_plan(
            db,
            user_id=user_id,
            content_id=content_id,
            content_title=content.title,
            platform=platform,
            platform_name=platform_config["name"],
            plan={},
            error=error,
        )
        return {"error": error}
    except Exception as e:
        logger.exception("Failed to generate creation plan for content %s", content_id)
        await _persist_creation_plan(
            db,
            user_id=user_id,
            content_id=content_id,
            content_title=content.title,
            platform=platform,
            platform_name=platform_config["name"],
            plan={},
            error=str(e),
        )
        return {"error": str(e)}


async def _persist_creation_plan(
    db: AsyncSession,
    *,
    user_id: int | None,
    content_id: int,
    content_title: str,
    platform: str,
    platform_name: str,
    plan: dict,
    error: str | None,
) -> None:
    """将创作方案持久化到 creation_plans 表（按用户隔离历史）。"""
    from app.models.creation import CreationPlan

    record = CreationPlan(
        user_id=user_id,  # 归属当前用户，用于创作历史隔离
        content_id=content_id,
        platform=platform,
        platform_name=platform_name,
        content_title_snapshot=content_title[:500],
        plan=plan,
        error=error,
    )
    db.add(record)
    try:
        await db.flush()
    except Exception:
        # 持久化失败不应阻塞主流程
        logger.warning("Persist creation plan failed (non-fatal)", exc_info=True)
        await db.rollback()
