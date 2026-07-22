"""
Monthly Digest LLM prompts.
"""

MONTHLY_DIGEST_PROMPT = """你是一位资深内容策划顾问。请根据以下本月精选内容数据，生成一份面向创作者的「精选月刊」。

## 本月内容数据（{month_label}）
{items_text}

## 本月分类统计
{category_text}

## 请严格按以下 JSON 格式输出：
{{
  "overview": "一段350字以内的本月热点概述，用专业且有洞察力的口吻，梳理本月最值得关注的内容趋势、长期变化和创作机会",
  "takeaway": "一句话核心要点，适合作为月刊标题/推送文案",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5", "关键词6"],
  "trends": [
    {{"title": "月度趋势标题", "desc": "趋势描述（60字内）", "color": "#3B82F6", "momentum": "up"}}
  ],
  "top_picks": [
    {{"rank": 1, "source_idx": 1, "source_title": "上方数据的原文标题（逐字复制，勿改写）", "title": "观点化选题标题（可改写为更吸引创作者的标题）", "source": "来源名称", "category": "分类", "reason": "中文摘要式推荐理由（70字内，概括核心信息+为什么值得写）", "score": 85, "platforms": ["公众号", "小红书"]}}
  ],
  "category_summary": {{
    "AI": {{"count": 5, "avg_score": 78, "top_title": "最热标题"}},
    "产品": {{"count": 3, "avg_score": 72, "top_title": "最热标题"}}
  }},
  "platform_tips": {{
    "公众号": ["本月创作建议1", "本月创作建议2"],
    "小红书": ["本月创作建议1", "本月创作建议2"],
    "视频号": ["本月创作建议1", "本月创作建议2"],
    "抖音": ["本月创作建议1"]
  }},
  "topic_clusters": [
    {{"name": "话题名称", "count": 5, "heat": 90, "representative_title": "代表文章标题"}}
  ],
  "action_items": [
    {{"title": "建议选题", "angle": "切入角度（30字内）", "difficulty": "简单/中等/困难", "platform": "推荐平台"}}
  ]
}}

要求：
- trends 给出 4-6 个本月内容趋势，momentum 为 up/down/stable
- top_picks 从上面数据中选 10-12 个最值得写的选题，按推荐度排序
- top_picks.source_idx 必须是上方数据中对应选题的序号（1-based），后端据此回链原文；source_title 必须逐字复制该序号对应的原文标题，不要改写或翻译
- top_picks.title 是你可以改写的观点化标题，source_title 是原文标题的精确引用，两者分开
- 不要编造 source_url，URL 由后端注入
- top_picks.reason 必须是中文摘要式推荐理由：先概括这条内容讲了什么，再说明为什么值得写；不要输出英文、不要营销夸张词、不要只写“建议关注/可以写”
- category_summary 按分类统计本月内容（count=数量, avg_score=平均创作分, top_title=该分类最热内容）
- platform_tips 给出各平台下月可执行的创作建议（每平台2-3条）
- topic_clusters 识别 4-8 个热门话题聚类
- action_items 给出 6-10 个可执行的下月创作建议，difficulty 为简单/中等/困难
- 明确体现月度复盘，不要写成日报或周报
- 所有文本用中文
- 只输出 JSON，不要其他内容"""
