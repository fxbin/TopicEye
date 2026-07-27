from __future__ import annotations

from collections import Counter
from typing import Any


def _text(value: Any, default: str = "") -> str:
    if value is None:
        return default
    return str(value).strip()


def _score(item: dict[str, Any]) -> float:
    for key in ("adjusted_score", "curation_score", "quality_score"):
        value = item.get(key)
        if isinstance(value, int | float):
            return float(value)
    return 0.0


def _top_categories(items: list[dict[str, Any]], limit: int = 6) -> list[str]:
    counter = Counter(_text(item.get("category"), "未分类") for item in items)
    return [name for name, _ in counter.most_common(limit)]


def _top_sources(items: list[dict[str, Any]], limit: int = 4) -> list[str]:
    counter = Counter(_text(item.get("source_name"), "未知来源") for item in items)
    return [name for name, _ in counter.most_common(limit)]


def build_digest_fallback(
    items: list[dict[str, Any]],
    *,
    label: str,
    top_limit: int = 8,
) -> dict[str, Any]:
    """Build a useful Chinese digest when the LLM returns empty or invalid JSON."""
    ranked = sorted(items, key=_score, reverse=True)
    categories = _top_categories(ranked)
    sources = _top_sources(ranked)
    top_items = ranked[:top_limit]

    top_picks = []
    for item in top_items:
        title = _text(item.get("title"), "未命名内容")
        summary = _text(item.get("summary"))
        recommendation = _text(item.get("recommendation"))
        reason_parts = [
            f"综合分约 {_score(item):.1f}",
            f"来自{_text(item.get('source_name'), '未知来源')}",
        ]
        if recommendation:
            reason_parts.append(recommendation[:80])
        elif summary:
            reason_parts.append(summary[:80])
        else:
            reason_parts.append("可作为后续人工筛选和创作判断的基础素材")

        top_picks.append(
            {
                "title": title,
                "reason": "；".join(reason_parts),
                "score": round(_score(item), 1),
                "platforms": ["公众号", "小红书", "短视频"],
                "source_url": _text(item.get("url")),
                "content_id": item.get("id"),
            }
        )

    category_summary = dict.fromkeys(categories, f"{label}内该方向素材较集中，适合继续观察选题密度和创作转化空间。")

    return {
        "overview": (
            f"LLM 暂时没有返回有效内容，系统已基于 {len(items)} 条已分析素材生成基础摘要。"
            f"当前素材主要集中在{('、'.join(categories) if categories else '未分类方向')}，"
            f"主要来源包括{('、'.join(sources) if sources else '多个信源')}。"
        ),
        "takeaway": "优先查看高分素材并补充人工判断；模型恢复后可重新生成更完整的趋势解读。",
        "keywords": categories[:5],
        "trends": [
            {
                "title": category,
                "desc": f"{category}方向在当前素材中出现频率较高，可作为候选选题池继续筛选。",
            }
            for category in categories[:5]
        ],
        "top_picks": top_picks,
        "category_summary": category_summary,
        "platform_tips": {
            "公众号": ["围绕高分素材补充背景、观点和案例，形成可沉淀的长文。"],
            "小红书": ["把单条素材拆成问题、经验或清单表达，优先测试互动反馈。"],
            "短视频": ["提炼冲突点和结论，用 30 秒解释为什么值得关注。"],
        },
        "topic_clusters": [
            {
                "name": category,
                "items": [item["title"] for item in top_items if _text(item.get("category"), "未分类") == category][:5],
            }
            for category in categories[:5]
        ],
        "action_items": [
            "检查本批高分素材是否已有收藏或创作方案。",
            "确认 LLM 路由链和模型返回是否稳定，必要时调整渠道优先级。",
            "模型恢复后重新生成摘要，以获得更完整的平台建议。",
        ],
    }


_DAILY_ANGLE_TEMPLATES: dict[str, list[str]] = {
    "模型发布": ["核对参数与部署门槛", "与上一代能力做对照", "换成真实任务验证"],
    "产品更新": ["拆解新功能的具体变化", "对照旧流程的使用成本", "验证谁会真正迁移"],
    "行业动态": ["还原事件中的利益关系", "区分短期信号与长期变化", "补充受影响者视角"],
    "技巧观点": ["整理可直接照做的步骤", "补一个失败或反例", "估算收益与使用成本"],
    "科研论文": ["用一句话解释研究问题", "看方法解决什么限制", "保留结论的适用边界"],
    "开源项目": ["给出复现或上手路径", "与同类工具做任务对照", "标出真实适用场景"],
}

_DAILY_TITLE_PREFIXES = ["先核对事实：", "值得拆开看：", "别只看标题：", "对创作者的含义："]


def _compact_title(value: str, limit: int = 30) -> str:
    text = " ".join(value.split())
    return text if len(text) <= limit else f"{text[:limit - 1]}…"


def _daily_platforms(category: str) -> list[str]:
    if category in {"科研论文", "模型发布"}:
        return ["公众号", "视频号"]
    if category in {"产品更新", "开源项目", "技巧观点"}:
        return ["公众号", "小红书", "视频号"]
    return ["公众号", "小红书"]


def _daily_reason(item: dict[str, Any]) -> str:
    summary = _text(item.get("summary"))
    recommendation = _text(item.get("recommendation"))
    if summary and recommendation:
        return f"{summary[:120]} 创作价值在于：{recommendation[:80]}"
    if summary:
        return f"{summary[:150]} 建议回到原文核对关键事实后，再决定是否跟进。"
    if recommendation:
        return f"{recommendation[:130]} 建议补足原文背景和具体案例，再形成自己的判断。"
    return "这条素材已进入当期优先池；先核对原文事实、适用范围和受影响对象，再确定表达角度。"


def build_daily_editorial_fallback(
    items: list[dict[str, Any]],
    *,
    label: str,
    top_limit: int = 8,
) -> dict[str, Any]:
    """Build a usable, editorially structured daily report without an LLM.

    The daily report remains a decision aid when a provider returns malformed
    JSON: it has a clear lead, a small feature set with concrete angles, and a
    scan-only brief list. Every claim is derived from the supplied items.
    """
    ranked = sorted(items, key=_score, reverse=True)[:top_limit]
    if not ranked:
        return build_digest_fallback([], label=label, top_limit=top_limit)

    categories = _top_categories(ranked)
    category_counts = Counter(_text(item.get("category"), "未分类") for item in ranked)
    lead = ranked[0]
    lead_title = _compact_title(_text(lead.get("title"), "首条素材"), 28)
    lead_category = _text(lead.get("category"), "重点方向")
    dominant_count = category_counts[lead_category]
    top_picks: list[dict[str, Any]] = []

    for index, item in enumerate(ranked, 1):
        source_title = _text(item.get("title"), "未命名内容")
        category = _text(item.get("category"), "未分类")
        feature = index <= min(3, len(ranked))
        pick: dict[str, Any] = {
            "source_idx": index,
            "source_title": source_title,
            "editorial_title": f"{_DAILY_TITLE_PREFIXES[(index - 1) % len(_DAILY_TITLE_PREFIXES)]}{_compact_title(source_title)}",
            "tier": "feature" if feature else "brief",
            "category": category,
            "reason": _daily_reason(item),
            "platforms": _daily_platforms(category),
            "source_url": _text(item.get("url")),
        }
        if feature:
            pick.update(
                {
                    "angles": _DAILY_ANGLE_TEMPLATES.get(
                        category,
                        ["先核对原文中的事实", "换一个具体对象切入", "补充适用范围与反例"],
                    ),
                    "pitfall": "单条素材不足以下行业结论；发布前请回到原文核对版本、数据和适用范围。",
                    "time_window": "建议今日或 48 小时内跟进",
                }
            )
        top_picks.append(pick)

    secondary_categories = [category for category in categories if category != lead_category][:2]
    contrast = f"，再用{'、'.join(secondary_categories)}做对照" if secondary_categories else ""
    overview = (
        f"今天先写「{lead_title}」：它是本期优先级最高的{lead_category}素材。"
        f"入选的 {len(ranked)} 条内容里，{lead_category}占 {dominant_count} 条{contrast}。"
        "写作时先讲清发生了什么、影响谁，再给出一个可验证的场景，避免把单条发布直接写成行业结论。"
    )

    return {
        "overview": overview,
        "takeaway": f"先写「{lead_title}」，别急着把单条信号当成趋势。",
        "keywords": categories[:5],
        "trends": [
            {
                "title": f"{category}信号集中",
                "desc": f"本期入选 {category_counts[category]} 条；当前仅反映当日素材分布，仍需后续追踪。",
                "momentum": "stable",
            }
            for category in categories[:3]
        ],
        "top_picks": top_picks,
        "platform_tips": {
            "公众号": [f"围绕「{lead_title}」按“事实—判断—下一步”展开，并附上原文依据。"],
            "小红书": [f"把「{lead_title}」拆成“发生了什么 / 对谁有影响 / 怎么判断”三张图卡。"],
            "视频号": [f"用 30 秒说明「{lead_title}」的一个关键信号，再给出一个具体场景。"],
        },
    }
