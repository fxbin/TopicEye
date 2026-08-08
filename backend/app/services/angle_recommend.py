"""AI 角度推荐 — 为热点话题生成"反差"创作角度

核心方法论（来自数字生命卡兹克）：
- 内容的本质是讲故事，信息搬运 ≠ 内容创作
- 找角度占 60%：反差/陌生化 = "情理之中，预料之外"
- 第一时间想到的角度一定不能写，因为所有人都会想到
- 好角度：让读者对熟悉的事物产生全新的理解

输出：
- common_angles: 大众常见角度（方便用户知道"不要写什么"）
- contrast_angles: 反差角度（1-2个真正有价值的创作方向）
- reasoning: 为什么这些角度有效（1-2句话）
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.llm import call_llm_json  # noqa: E402
from app.services.llm.prompts.angle_recommend import SYSTEM_PROMPT, USER_TEMPLATE
from app.utils.prompt_safety import sanitize_prompt_input

logger = logging.getLogger(__name__)


async def generate_angles_for_topic(
    topic: str,
    keywords: list[str],
    platform_titles: list[str],
) -> dict[str, Any]:
    """
    为一个热点话题生成反差角度推荐。

    Args:
        topic: 话题标题（代表性的最短标题）
        keywords: 关键词列表
        platform_titles: 各平台原始标题列表

    Returns:
        {
            "common_angles": [...],
            "contrast_angles": [{"angle": "...", "reasoning": "..."}, ...],
            "angle_note": "...",
        }
    """
    # 防御 prompt injection：统一用 sanitize_prompt_input 清洗
    clean_topic = sanitize_prompt_input(topic, max_chars=40)
    clean_keywords = sanitize_prompt_input(", ".join(keywords), max_chars=200)
    clean_titles = sanitize_prompt_input("\n".join(f"- {t}" for t in platform_titles[:8]), max_chars=2000)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                topic=clean_topic,
                keywords=clean_keywords,
                titles=clean_titles,
            ),
        },
    ]

    result = await call_llm_json(
        messages,
        temperature=0.3,
        max_tokens=800,
        scene="angle_recommend",
    )

    # 防御：如果 LLM 返回格式不对
    if not isinstance(result, dict):
        return {
            "common_angles": [],
            "contrast_angles": [],
            "angle_note": "角度生成失败",
        }

    return {
        "common_angles": result.get("common_angles", [])[:3],
        "contrast_angles": [
            {
                "angle": a.get("angle", ""),
                "reasoning": a.get("reasoning", ""),
            }
            for a in result.get("contrast_angles", [])[:2]
        ],
        "angle_note": result.get("angle_note", ""),
    }
