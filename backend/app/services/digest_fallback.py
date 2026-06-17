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
        if isinstance(value, (int, float)):
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
            }
        )

    category_summary = {
        category: f"{label}内该方向素材较集中，适合继续观察选题密度和创作转化空间。" for category in categories
    }

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
