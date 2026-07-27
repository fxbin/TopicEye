"""
AI Semantic Deduplication.

Replaces the SequenceMatcher-based title dedup with LLM-powered semantic analysis.
Handles cross-language, paraphrasing, and different descriptions of the same event.

Algorithm:
  1. Group candidate items (limit batch to BATCH_SIZE to control cost)
  2. For each batch: send title + summary + tags to LLM
  3. LLM returns {(duplicate_id): canonical_id} pairs
  4. Caller writes to DB via UPDATE content_items SET duplicate_of=:can_id
"""

from __future__ import annotations

import asyncio
import json
import logging

from app.services.llm import call_llm_json

logger = logging.getLogger(__name__)

# Max items per LLM dedup batch — keeps token cost predictable
BATCH_SIZE = 20
SEMANTIC_DEDUP_CONCURRENCY = 3

# Fields included in the prompt per item
ITEM_FIELDS = ("id", "title", "summary", "tags", "source_name", "curation_score")


def _build_item_summary(item: dict) -> str:
    """Format one item for the LLM prompt."""
    parts = [
        f"[ID {item['id']}]",
        f"标题: {item.get('title', '')}",
    ]
    if item.get("summary"):
        parts.append(f"摘要: {item.get('summary', '')[:200]}")
    if item.get("tags"):
        tags = item["tags"]
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except Exception:
                tags = []
        if isinstance(tags, list):
            parts.append(f"标签: {', '.join(str(t) for t in tags[:5])}")
    if item.get("source_name"):
        parts.append(f"来源: {item['source_name']}")
    return " | ".join(parts)


async def _dedup_one_batch(items: list[dict]) -> dict[int, int]:
    """
    Ask LLM to find duplicates within a batch of items.

    Returns {duplicate_id: canonical_id}.
    Items are considered duplicates if they describe the SAME actual event/news,
    not just similar topics.

    Canonical = item with highest curation_score (best quality source wins).
    """
    if len(items) < 2:
        return {}

    item_summaries = "\n\n".join(_build_item_summary(item) for item in items)

    prompt = [
        {
            "role": "user",
            "content": (
                "以下是一批内容，请判断哪些是「同一条新闻/事件的重复报道」。\n"
                "注意区分：\n"
                "  - 「同事件」：同一个具体新闻、同一产品更新、同一个人物的同一个动态\n"
                "  - 「相似话题」：都是AI新闻但不是同一条（不算重复）\n\n"
                f"{item_summaries}\n\n"
                "请以JSON格式返回所有重复对：\n"
                '  {"duplicates": [[canonical_id, duplicate_id], [canonical_id, duplicate_id], ...]}\n\n'
                "规则：\n"
                "  - canonical_id 选质量分（curation_score）高的那条\n"
                "  - 只输出真正描述同一事件的，不要强行配对\n"
                "  - 完全不同的内容不要输出\n"
                '  - 如果没有重复对，返回 {"duplicates": []}\n'
                "  - id 必须是上面列表中存在的ID\n"
            ),
        }
    ]

    try:
        data = await call_llm_json(prompt, temperature=0.1, max_tokens=1500, scene="semantic_dedup")
        raw = data.get("duplicates", [])
        if not isinstance(raw, list):
            logger.warning("semantic_dedup: unexpected LLM response type %s", type(raw))
            return {}

        result: dict[int, int] = {}
        valid_ids = {int(item["id"]) for item in items}
        scored = {item["id"]: item.get("curation_score", 0) for item in items}

        for pair in raw:
            if not isinstance(pair, list | tuple) or len(pair) < 2:
                continue
            try:
                can_id = int(pair[0])
                dup_id = int(pair[1])
            except (ValueError, TypeError):
                continue

            if can_id == dup_id:
                continue
            if can_id not in valid_ids or dup_id not in valid_ids:
                logger.warning(
                    "semantic_dedup: ignored duplicate pair outside batch ids: %s -> %s",
                    dup_id,
                    can_id,
                )
                continue
            # Ensure canonical has the higher score
            if scored.get(dup_id, 0) > scored.get(can_id, 0):
                can_id, dup_id = dup_id, can_id

            result[dup_id] = can_id

        logger.info("semantic_dedup batch: %d items → %d duplicate pairs", len(items), len(result))
        return result

    except Exception as exc:
        logger.warning("semantic_dedup LLM call failed: %s", exc)
        return {}


async def semantic_dedup(items: list[dict]) -> dict[int, int]:
    """
    Run AI semantic dedup on a list of content items.

    Args:
        items: list of dict with at least id, title, summary, tags, curation_score

    Returns:
        {duplicate_id: canonical_id} for all detected duplicates
    """
    if not items:
        return {}

    all_dups: dict[int, int] = {}
    n = len(items)

    batches = [items[start : start + BATCH_SIZE] for start in range(0, n, BATCH_SIZE)]
    semaphore = asyncio.Semaphore(SEMANTIC_DEDUP_CONCURRENCY)

    async def _run_batch(batch: list[dict]) -> dict[int, int]:
        async with semaphore:
            return await _dedup_one_batch(batch)

    for dups in await asyncio.gather(*(_run_batch(batch) for batch in batches)):
        all_dups.update(dups)

    logger.info("semantic_dedup total: %d items → %d duplicate pairs", n, len(all_dups))
    return all_dups
