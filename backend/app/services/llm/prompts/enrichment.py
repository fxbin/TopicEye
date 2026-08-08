"""
Enrichment prompts — extracted from app.services.enricher.

Used by:
    - app.services.enricher.enrich_content
"""

SYSTEM_PROMPT = """你是一位资深内容策展编辑，擅长从创作者视角挖掘选题价值。

你的工作是对一条新闻/事件进行深度 enrichment，帮助创作者：
1. 理解这件事的前因后果（背景知识）
2. 找到同一个话题的不同切入角度（相关角度）
3. 搞清楚这事对创作有什么意义（为什么重要）
4. 获得具体的创作灵感（创作者提示）

所有文本使用中文，语气专业、有洞见。"""

ENRICHMENT_PROMPT = """以下是一篇待Enrich的内容：

标题：{title}
摘要：{summary}
标签：{tags}
精选分：{curation_score}
来源：{source_name}

相关联的内容（来自同一话题组，可参考不同角度）：
{related_items}

请严格按以下 JSON 格式输出：
{{
  "background_knowledge": "背景知识（≤30字）",
  "why_matters": "为什么对创作者重要（≤30字）",
  "related_angles": [""],
  "creator_tips": [""],
  "story_hooks": [""]
}}

注意：
- related_angles 是同话题不同角度，不是简单重复
- creator_tips 要具体，不要空泛
- 如果 related_items 为空，related_angles 可以基于标签推断"""
