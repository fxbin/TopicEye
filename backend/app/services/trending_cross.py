"""跨平台热点交叉发现

核心逻辑：
1. 取所有 trending_items（~400条）
2. jieba 分词提取关键词
3. 标题间 Jaccard 相似度 + 共同关键词数
4. 贪心聚类：将相似标题归为同一"共振话题"
5. 计算共振强度（出现在 N 个平台 = N次共振）
"""

from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import List, Dict, Any

import jieba
import jieba.analyse
from app.services.zhihu_url import normalize_zhihu_url

logger = logging.getLogger(__name__)

# 停用词
_STOPWORDS = set(
    ["的了是在我有和就不人都一上也他到说这着你要会把她被从让用为以及于对与或但而如果因为所以这个那个什么怎么哪谁几多大小里外中前后上下左右来自往向然后然后虽然但是不过可是然后可以可能已经这些那些其实事实上真的非常还更最就才只又再"]
)

# 信源显示名
_SOURCE_LABELS: dict[str, str] = {
    "weibo": "微博",
    "baidu": "百度",
    "douyin": "抖音",
    "toutiao": "头条",
    "zhihu": "知乎",
    "bilibili": "B站",
    "hackernews": "HN",
    "ithome": "IT之家",
    "juejin": "掘金",
    "eastmoney": "东方财富",
}


def _extract_keywords(title: str, topk: int = 8) -> list[str]:
    """提取标题关键词（用 TF-IDF）"""
    words = jieba.analyse.extract_tags(title, topK=topk, withWeight=False)
    # 过滤停用词和单字
    return [w for w in words if len(w) >= 2 and w not in _STOPWORDS]


def _jaccard(set_a: set, set_b: set) -> float:
    if not set_a or not set_b:
        return 0.0
    intersection = set_a & set_b
    union = set_a | set_b
    return len(intersection) / len(union)


def _title_similarity(kw_a: set, kw_b: set) -> float:
    """综合相似度：Jaccard + 共同关键词加分"""
    if not kw_a or not kw_b:
        return 0.0
    common = kw_a & kw_b
    if not common:
        return 0.0
    j = len(common) / len(kw_a | kw_b)
    # 共同关键词越多，加分越多
    bonus = min(len(common) / 3.0, 1.0) * 0.3
    return j + bonus


def cluster_trending_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    对 trending_items 做跨平台聚类。

    输入：[{id, source, category, rank, title, hot_value, ...}, ...]
    输出：[{
        topic: str,              # 代表性标题
        keywords: [str],         # 关键词
        resonance: int,          # 共振平台数
        sources: [str],          # 出现的平台列表
        source_labels: [str],    # 平台中文名
        items: [{...}],          # 原始条目
        total_hot: int,          # 总热度
        avg_rank: float,         # 平均排名
    }, ...]
    """
    if not items:
        return []

    # 1. 提取关键词
    item_kw: dict[int, set] = {}
    for item in items:
        kws = _extract_keywords(item["title"])
        item_kw[item["id"]] = set(kws)
        item["_keywords"] = kws

    # 2. 贪心聚类
    SIM_THRESHOLD = 0.25  # 相似度阈值
    used = set()
    clusters: list[list[dict]] = []

    # 按热度排序，优先处理高热度
    sorted_items = sorted(items, key=lambda x: x.get("hot_value", 0), reverse=True)

    for item in sorted_items:
        iid = item["id"]
        if iid in used:
            continue

        # 开始一个新簇
        cluster = [item]
        used.add(iid)
        kw_set = item_kw[iid]

        # 找所有相似的未使用条目
        for other in sorted_items:
            oid = other["id"]
            if oid in used:
                continue
            sim = _title_similarity(kw_set, item_kw[oid])
            if sim >= SIM_THRESHOLD:
                cluster.append(other)
                used.add(oid)

        clusters.append(cluster)

    # 3. 组装结果
    results: list[dict[str, Any]] = []
    for cluster in clusters:
        # 只返回跨平台或多条目的（单条目也保留，方便前端展示）
        sources_set = set(it["source"] for it in cluster)
        resonance = len(sources_set)

        # 选最短标题作为代表（通常最精炼）
        rep_title = min(cluster, key=lambda x: len(x["title"]))["title"]

        # 合并关键词
        all_kw: dict[str, int] = defaultdict(int)
        for it in cluster:
            for kw in it.get("_keywords", []):
                all_kw[kw] += 1
        top_keywords = sorted(all_kw, key=all_kw.get, reverse=True)[:6]

        total_hot = sum(it.get("hot_value", 0) for it in cluster)
        avg_rank = sum(it.get("rank", 0) for it in cluster) / len(cluster)

        # 每个平台取排名最高的那条
        by_source: dict[str, dict] = {}
        for it in cluster:
            s = it["source"]
            if s not in by_source or it["rank"] < by_source[s]["rank"]:
                by_source[s] = it

        results.append(
            {
                "topic": rep_title,
                "keywords": top_keywords,
                "resonance": resonance,
                "item_count": len(cluster),
                "sources": sorted(sources_set),
                "source_labels": [_SOURCE_LABELS.get(s, s) for s in sorted(sources_set)],
                "source_items": [
                    {
                        "source": s,
                        "source_label": _SOURCE_LABELS.get(s, s),
                        "title": by_source[s]["title"],
                        "rank": by_source[s]["rank"],
                        "hot_value": by_source[s].get("hot_value", 0),
                        "hot_value_raw": by_source[s].get("hot_value_raw", ""),
                        "url": normalize_zhihu_url(by_source[s].get("url", "")),
                        "trend": by_source[s].get("trend"),
                    }
                    for s in sorted(sources_set)
                ],
                "items": cluster,
                "total_hot": total_hot,
                "avg_rank": round(avg_rank, 1),
            }
        )

    # 按共振强度降序，再按总热度降序
    results.sort(key=lambda x: (x["resonance"], x["total_hot"]), reverse=True)
    return results
