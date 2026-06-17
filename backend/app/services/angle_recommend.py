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
import re
from typing import Any

from app.services.llm import call_llm_json  # noqa: E402

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是一个资深内容策划师，擅长为热点话题找到独特的创作角度。
你的方法论来自行业顶尖爆款号的经验：
1. 第一直觉想到的角度一定不能写——那是最大众化的角度，写了也不会爆
2. 真正有价值的角度是"陌生化"：让读者对一个熟悉的话题产生全新理解
3. 反差角度的核心是"情理之中，预料之外"：看似不合理，但逻辑自洽
4. 时刻想着"这个话题的所有人都会怎么写"——然后写相反的

你的任务是分析给定的热点话题，生成：
- common_angles: 大众常见角度（帮用户排除）
- contrast_angles: 反差角度（真正值得写的）
- angle_rationale: 为什么这个反差角度有效

回答要精准、有洞察、面向内容创作者。不要废话。"""

USER_TEMPLATE = """请分析以下热点话题，生成创作角度推荐。

话题：{topic}

关键词：{keywords}

平台原始标题：
{titles}

请生成以下JSON格式的回答（严格JSON，不要有其他文字）：
{{"common_angles": ["角度1", "角度2", "角度3"], "contrast_angles": [{{"angle": "反差角度描述", "reasoning": "为什么这个角度有效"}}, {{"angle": "另一个反差角度", "reasoning": "为什么有效"}}], "angle_note": "一句话总结这个话题的核心创作洞察"}}
"""


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
    # 防御 prompt injection：清洗用户输入，移除控制字符，限制长度
    clean_topic = re.sub(r"[\x00-\x1f\x7f]", "", topic)[:40]
    clean_keywords = re.sub(r"[\x00-\x1f\x7f]", "", ", ".join(keywords))[:200]
    clean_titles = "\n".join(f"- {t}" for t in platform_titles[:8])
    # 限制标题总长度，防止超长输入耗尽 LLM token
    if len(clean_titles) > 2000:
        clean_titles = clean_titles[:2000] + "\n...(truncated)"

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
