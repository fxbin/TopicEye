"""
Dedup prompts — extracted from app.services.semantic_dedup.

Note: The original semantic_dedup.py constructs its prompt inline
in _dedup_one_batch() rather than using module-level constants.
This module provides equivalent standalone constants for future use
when the service is refactored to import from here.
"""

SYSTEM_PROMPT = (
    "你是一个内容去重分析助手。你需要判断一批内容中哪些是「同一条新闻/事件的重复报道」，而不是仅仅「相似话题」。"
)

DEDUP_PROMPT = """以下是一批内容，请判断哪些是「同一条新闻/事件的重复报道」。
注意区分：
  - 「同事件」：同一个具体新闻、同一产品更新、同一个人物的同一个动态
  - 「相似话题」：都是AI新闻但不是同一条（不算重复）

{item_summaries}

请以JSON格式返回所有重复对：
  {{"duplicates": [[canonical_id, duplicate_id], [canonical_id, duplicate_id], ...]}}

规则：
  - canonical_id 选质量分（curation_score）高的那条
  - 只输出真正描述同一事件的，不要强行配对
  - 完全不同的内容不要输出
  - 如果没有重复对，返回 {{"duplicates": []}}
  - id 必须是上面列表中存在的ID"""
