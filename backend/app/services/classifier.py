"""
Content classification and tag extraction service.

Dual-mode classifier:
- **Async (LLM)**: Uses AI to dynamically classify content into existing
  or new categories. New categories are auto-registered in the database.
- **Sync (keyword fallback)**: Pure keyword matching for when LLM is
  unavailable (startup, rate-limit, offline).

The sync path is unchanged from the original implementation and serves as
a zero-dependency fallback.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# ── Keyword-based fallback (unchanged) ─────────────────────────────────

CATEGORIES: list[str] = [
    "AI",
    "职场",
    "商业",
    "教育",
    "自媒体",
    "科技",
    "生活",
    "产品",
    "情感",
    "其他",
]

# ── 内容形态（双轴分类的 format 轴） ────────────────────────────────
# 与 category（主题轴）正交，描述内容的呈现形态/意图
CONTENT_TYPES: list[str] = [
    "论文",  # 学术论文 / 预印本
    "技术",  # 技术文章 / 工程实践
    "资讯",  # 新闻 / 行业动态
    "教程",  # 教程 / 指南 / How-to
    "观点",  # 评论 / 分析 / 观点
    "工具",  # 工具 / 产品发布
    "体验",  # 体验测评 / 用户研究
    "成长",  # 个人成长 / 思维方法
    "讨论",  # 社区讨论 / 问答
    "项目",  # 开源项目 / Side Project
]

# 信源 category 中 `/` 后的形态别名 -> 标准化 content_type
_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "论文": "论文",
    "paper": "论文",
    "学术": "论文",
    "技术": "技术",
    "tech": "技术",
    "资讯": "资讯",
    "新闻": "资讯",
    "news": "资讯",
    "教程": "教程",
    "tutorial": "教程",
    "指南": "教程",
    "观点": "观点",
    "评论": "观点",
    "opinion": "观点",
    "工具": "工具",
    "tool": "工具",
    "产品": "工具",
    "体验": "体验",
    "review": "体验",
    "测评": "体验",
    "成长": "成长",
    "思维": "成长",
    "讨论": "讨论",
    "discussion": "讨论",
    "项目": "项目",
    "project": "项目",
    "开源": "项目",
}

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "AI": [
        "AI",
        "GPT",
        "ChatGPT",
        "LLM",
        "OpenAI",
        "Claude",
        "DeepSeek",
        "大模型",
        "人工智能",
        "机器学习",
        "Agent",
        "Prompt",
        "transformer",
        "diffusion",
        "RAG",
        "fine-tune",
        "微调",
        "神经网络",
        "深度学习",
    ],
    "职场": [
        "职场",
        "工作",
        "月薪",
        "跳槽",
        "副业",
        "辞职",
        "转行",
        "打工人",
        "上班",
        "摸鱼",
        "简历",
        "面试",
        "offer",
        "薪资",
        "加班",
        "晋升",
    ],
    "商业": [
        "商业",
        "创业",
        "融资",
        "上市",
        "商业模式",
        "变现",
        "营收",
        "电商",
        "投资",
        "IPO",
        "独角兽",
        "B2B",
        "B2C",
        "SaaS",
        "利润",
        "亏损",
    ],
    "教育": [
        "教育",
        "考研",
        "考公",
        "学习",
        "课程",
        "学历",
        "大学",
        "培训",
        "考试",
        "高考",
        "留学",
        "英语",
        "备考",
        "上岸",
        "知识付费",
    ],
    "自媒体": [
        "自媒体",
        "涨粉",
        "运营",
        "IP",
        "粉丝",
        "账号",
        "内容创作",
        "博主",
        "短视频",
        "直播",
        "带货",
        "流量",
        "爆款",
        "选题",
        "MCN",
    ],
    "科技": [
        "科技",
        "Apple",
        "WWDC",
        "iOS",
        "Android",
        "芯片",
        "手机",
        "硬件",
        "开源",
        "Google",
        "Microsoft",
        "Meta",
        "特斯拉",
        "5G",
        "云计算",
        "量子",
        "无人机",
        "机器人",
        "半导体",
    ],
    "生活": [
        "生活",
        "旅行",
        "美食",
        "健康",
        "健身",
        "穿搭",
        "宠物",
        "家居",
        "装修",
        "租房",
        "理财",
        "保险",
        "养老",
        "收纳",
        "极简",
    ],
    "产品": [
        "产品",
        "用户体验",
        "需求",
        "设计",
        "功能",
        "竞品",
        "发布",
        "更新",
        "MVP",
        "迭代",
        "原型",
        "交互",
        "UI",
        "UX",
        "AB测试",
        "PM",
    ],
    "情感": [
        "情感",
        "恋爱",
        "婚姻",
        "分手",
        "暗恋",
        "表白",
        "离婚",
        "相亲",
        "异地恋",
        "三观",
        "星座",
        "治愈",
        "孤独",
        "成长",
    ],
}

# Build a flat keyword -> category lookup (lower-case for matching)
_KEYWORD_MAP: dict[str, str] = {}
for _cat, _kws in CATEGORY_KEYWORDS.items():
    for _kw in _kws:
        _KEYWORD_MAP[_kw.lower()] = _cat


def classify(text: str) -> str:
    """
    Sync keyword-based classification (fallback).

    Returns the category with the most keyword hits; falls back to "其他".
    """
    if not text:
        return "其他"

    text_lower = text.lower()
    scores: Counter[str] = Counter()
    for keyword, category in _KEYWORD_MAP.items():
        if keyword in text_lower:
            scores[category] += 1

    if not scores:
        return "其他"

    return scores.most_common(1)[0][0]


def _normalize_content_type(value: str | None) -> str | None:
    """将信源 category 中的形态部分或 LLM 返回的 content_type 标准化。

    >>> _normalize_content_type("论文")
    '论文'
    >>> _normalize_content_type("paper")
    '论文'
    >>> _normalize_content_type("")
    None
    """
    if not value:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    # 精确匹配优先
    if key in _CONTENT_TYPE_ALIASES:
        return _CONTENT_TYPE_ALIASES[key]
    # 原值回退（允许新形态值透传，但截断长度）
    return str(value).strip()[:50]


def _get_keyword_score(text: str) -> float:
    """
    Returns a 0.0-1.0 confidence score for keyword-based classification.
    1.0 = strong keyword hit (multiple keywords in same category)
    0.0 = no keywords matched
    """
    if not text:
        return 0.0

    text_lower = text.lower()
    scores: Counter[str] = Counter()
    for keyword, category in _KEYWORD_MAP.items():
        if keyword in text_lower:
            scores[category] += 1

    if not scores:
        return 0.0

    top_count = scores.most_common(1)[0][1]
    # Normalize: 1 keyword hit = 0.4, 2 hits = 0.7, 3+ = 1.0
    score = min(1.0, (top_count - 1) * 0.3 + 0.4)
    return score


def extract_tags(text: str, max_tags: int = 5) -> list[str]:
    """
    Extract relevant keyword tags from *text* (sync fallback).
    """
    if not text:
        return []

    text_lower = text.lower()
    matched: Counter[str] = Counter()
    for keyword in _KEYWORD_MAP:
        count = text_lower.count(keyword)
        if count > 0:
            matched[keyword] = count

    sorted_tags = sorted(matched.keys(), key=lambda k: (-matched[k], k))
    return sorted_tags[:max_tags]


# ── LLM-powered async classification ────────────────────────────────────


async def classify_async(
    title: str,
    summary: str,
    db: AsyncSession | None,
    category_names: list[str] | None = None,
    auto_create_new_category: bool = True,
) -> dict[str, Any]:
    """
    Classify content using LLM with dynamic category discovery.

    Fast-path: keyword fallback is tried FIRST. If confidence is high
    enough (>=0.4 keyword score), skip LLM entirely and use keyword result.
    Only falls back to LLM when keyword score is low (category=其他 or low score).

    Returns:
        {
            "category": str,          # 分类名称
            "content_type": str|None, # 内容形态（论文/技术/资讯/...）
            "tags": list[str],        # 关键词标签
            "is_new_category": bool,  # 是否为新发现的分类
            "confidence": float,      # 置信度
        }
    """
    from app.repositories.category_repo import CategoryRepository
    from app.services.llm import call_llm_json
    from app.services.llm.prompts.classification import (
        CLASSIFICATION_PROMPT,
        SYSTEM_PROMPT,
    )
    from app.utils.prompt_safety import sanitize_prompt_input

    # Get current category list for the prompt. Ingestion can pass a per-source
    # snapshot to avoid one DB query per new item.
    cat_repo: CategoryRepository | None = None
    if category_names is None:
        if db is None:
            category_names = CATEGORIES.copy()
        else:
            cat_repo = CategoryRepository(db)
            category_names = await cat_repo.get_active_names()

    # If no categories in DB yet, use the hardcoded list as seed
    if not category_names:
        category_names = CATEGORIES.copy()
    allowed_categories = {name.strip() for name in category_names if name and name.strip()}

    text_input = f"{title} {summary}".strip()

    # ── Fast-path: keyword fallback first (no I/O, no LLM call) ──────────
    keyword_category = classify(text_input)
    keyword_tags = extract_tags(text_input)
    keyword_score = _get_keyword_score(text_input)  # 0.0 ~ 1.0

    # If keyword hit a known category with decent score, skip LLM entirely
    # This avoids one LLM API call per content item during bulk ingestion
    if keyword_category != "其他" and keyword_score >= 0.4:
        return {
            "category": keyword_category,
            "content_type": None,  # keyword fast-path 不判定形态
            "tags": keyword_tags,
            "is_new_category": False,
            "confidence": keyword_score,
        }

    # ── Slow path: LLM classification ─────────────────────────────────────
    categories_str = "、".join(category_names)

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": CLASSIFICATION_PROMPT.format(
                    categories=sanitize_prompt_input(categories_str, max_chars=500),
                    title=sanitize_prompt_input(title, max_chars=500),
                    summary=sanitize_prompt_input(summary or "无摘要", max_chars=500),
                ),
            },
        ]

        result = await call_llm_json(
            messages,
            temperature=0.1,
            max_tokens=300,
            scene="classification",
        )

        category = _normalize_category_name(result.get("category"))
        content_type = _normalize_content_type(result.get("content_type"))
        tags = _normalize_llm_tags(result.get("tags"))
        # 显式 bool 解析：bool("false") 在 Python 是 True，弱模型返回字符串会污染分类表
        _raw_new = result.get("is_new_category", False)
        is_new = _raw_new if isinstance(_raw_new, bool) else str(_raw_new).strip().lower() in ("true", "1", "yes")
        confidence = _clamp_confidence(result.get("confidence", 0.5))

        if not category:
            raise ValueError("Empty category from LLM")
        if category not in allowed_categories and not is_new:
            raise ValueError(f"Unknown category from LLM: {category}")

        # Auto-register new category
        if is_new and auto_create_new_category:
            try:
                if cat_repo is None:
                    if db is None:
                        raise RuntimeError("db session required to auto-create category")
                    cat_repo = CategoryRepository(db)
                await cat_repo.get_or_create(
                    name=category,
                    description="LLM自动发现的分类",
                    is_auto_created=True,
                )
            except Exception as e:
                logger.warning("Failed to auto-create category '%s': %s", category, e)

        return {
            "category": category,
            "content_type": content_type,
            "tags": tags,
            "is_new_category": is_new,
            "confidence": confidence,
        }

    except Exception as exc:
        logger.warning("LLM classification failed, falling back to keywords: %s", exc)
        category = classify(text_input)
        tags = extract_tags(text_input)
        return {
            "category": category,
            "content_type": None,
            "tags": tags,
            "is_new_category": False,
            "confidence": 0.3,
        }


def _normalize_category_name(value: Any) -> str:
    category = str(value or "").strip()
    return category[:100]


def _normalize_llm_tags(value: Any, *, max_tags: int = 5) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (json.JSONDecodeError, TypeError):
            value = [value]
    if not isinstance(value, list):
        return []

    tags: list[str] = []
    for raw in value:
        tag = str(raw or "").strip()
        if not tag or tag in tags:
            continue
        tags.append(tag[:40])
        if len(tags) >= max_tags:
            break
    return tags


def _clamp_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


async def seed_categories(db: AsyncSession) -> int:
    """
    Initialize the categories table with seed data from the hardcoded list.

    Run once on first startup (or when DB is fresh).
    Returns the number of categories created.
    """
    from app.repositories.category_repo import CategoryRepository

    cat_repo = CategoryRepository(db)
    created = 0

    for name, keywords in CATEGORY_KEYWORDS.items():
        existing = await cat_repo.get_by_name(name)
        if not existing:
            await cat_repo.create(
                name=name,
                description=f"{name}相关内容",
                keywords=",".join(keywords),
                is_auto_created=False,
                is_active=True,
                content_count=0,
            )
            created += 1

    # Also add "其他" if missing
    other = await cat_repo.get_by_name("其他")
    if not other:
        await cat_repo.create(
            name="其他",
            description="未匹配到具体分类的内容",
            is_auto_created=False,
            is_active=True,
            content_count=0,
        )
        created += 1

    if created > 0:
        logger.info("Seeded %d categories", created)

    return created
