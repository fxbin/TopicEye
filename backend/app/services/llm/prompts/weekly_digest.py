"""
Weekly Digest LLM prompts — extracted for maintainability.

Used by:
    - app.services.weekly_digest.generate_weekly_digest
"""

WEEKLY_DIGEST_PROMPT = """你是一位资深内容策划顾问。请根据以下本周精选内容数据，生成一份面向创作者的「精选周刊」。

## 本周内容数据（{week_label}）
{items_text}

## 本周分类统计
{category_text}

## 请严格按以下 JSON 格式输出：
{{
  "overview": "一段300字以内的本周热点概述，用专业且有洞察力的口吻，梳理本周最值得关注的内容趋势和行业动态",
  "takeaway": "一句话核心要点，适合作为周刊标题/推送文案",
  "keywords": [""],
  "trends": [
    {{"title": "", "desc": "趋势描述（≤50字）", "color": "#3B82F6", "momentum": "up"}}
  ],
  "top_picks": [
    {{"rank": 1, "source_idx": 1, "source_title": "逐字复制上方数据原文标题", "title": "观点化选题标题", "source": "", "category": "", "reason": "中文摘要式推荐理由（≤60字，概括核心信息+为什么值得写）", "score": 85, "platforms": ["公众号"]}}
  ],
  "category_summary": {{
    "AI": {{"count": 5, "avg_score": 78, "top_title": ""}}
  }},
  "platform_tips": {{
    "公众号": [""],
    "小红书": [""]
  }},
  "topic_clusters": [
    {{"name": "", "count": 5, "heat": 90, "representative_title": ""}}
  ],
  "action_items": [
    {{"title": "", "angle": "切入角度（≤30字）", "difficulty": "简单/中等/困难", "platform": ""}}
  ]
}}

要求：
- trends 给出 3-5 个本周内容趋势，momentum 为 up/down/stable
- top_picks 从上面数据中选 8-10 个最值得写的选题，按推荐度排序
- top_picks.source_idx 必须是上方数据中对应选题的序号（1-based），后端据此回链原文；source_title 必须逐字复制该序号对应的原文标题，不要改写或翻译
- top_picks.title 是你可以改写的观点化标题，source_title 是原文标题的精确引用，两者分开
- 不要编造 source_url，URL 由后端注入
- top_picks.reason 必须是中文摘要式推荐理由：先概括这条内容讲了什么，再说明为什么值得写；不要输出英文、不要营销夸张词、不要只写“建议关注/可以写”
- category_summary 按分类统计本周内容（count=数量, avg_score=平均创作分, top_title=该分类最热内容）
- platform_tips 给出各平台本周的创作建议（每平台2-3条）
- topic_clusters 识别 3-6 个热门话题聚类
- action_items 给出 5-8 个可执行的创作建议，difficulty 为简单/中等/困难
- 所有文本用中文
- 只输出 JSON，不要其他内容"""
