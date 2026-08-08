"""
Digest LLM prompts — unified template for weekly and monthly digests.

Used by:
    - app.services.weekly_digest.generate_weekly_digest
    - app.services.monthly_digest.generate_monthly_digest

Both prompts share the same JSON schema and rules. The only differences
are period label, item limits, and overview length — passed as format
parameters via ``DIGEST_PROMPT.format(...)``.
"""

# ── Unified digest prompt template ────────────────────────────
#
# Format parameters:
#   {period_label}       — "5月19日 ~ 5月25日" or "2026年7月"
#   {period_word}        — "本周" / "本月" / "下月"  (used in requirement bullets)
#   {items_text}         — pre-built items text (top N items, 1-based indexed)
#   {category_text}      — pre-built category statistics text
#   {overview_limit}     — max overview length in chars (300 / 350)
#   {trend_count}        — "3-5" / "4-6"
#   {picks_count}        — "8-10" / "10-12"
#   {cluster_count}      — "3-6" / "4-8"
#   {action_count}       — "5-8" / "6-10"
#   {reason_limit}       — "60" / "70"  (max chars for pick reason)
#   {trend_desc_limit}   — "50" / "60"  (max chars for trend description)
#   {period_note}        — extra instruction for monthly (e.g. "明确体现月度复盘，不要写成日报或周报") or empty string

DIGEST_PROMPT = """你是一位资深内容策划顾问。请根据以下{period_word}精选内容数据，生成一份面向创作者的「精选{digest_type}」。

## {period_label}内容数据（{period_label}）
{items_text}

## {period_word}分类统计
{category_text}

## 请严格按以下 JSON 格式输出：
{{
  "overview": "一段{overview_limit}字以内的{period_word}热点概述，用专业且有洞察力的口吻，梳理{period_word}最值得关注的内容趋势和行业动态",
  "takeaway": "一句话核心要点，适合作为{digest_type}标题/推送文案",
  "keywords": ["关键词1", "关键词2", "关键词3", "关键词4", "关键词5", "关键词6"],
  "trends": [
    {{"title": "趋势标题", "desc": "趋势描述（{trend_desc_limit}字内）", "color": "#3B82F6", "momentum": "up"}}
  ],
  "top_picks": [
    {{"rank": 1, "source_idx": 1, "source_title": "上方数据的原文标题（逐字复制，勿改写）", "title": "观点化选题标题（可改写为更吸引创作者的标题）", "source": "来源名称", "category": "分类", "reason": "中文摘要式推荐理由（{reason_limit}字内，概括核心信息+为什么值得写）", "score": 85, "platforms": ["公众号", "小红书"]}}
  ],
  "category_summary": {{
    "AI": {{"count": 5, "avg_score": 78, "top_title": "最热标题"}},
    "产品": {{"count": 3, "avg_score": 72, "top_title": "最热标题"}}
  }},
  "platform_tips": {{
    "公众号": ["{period_word}创作建议1", "{period_word}创作建议2"],
    "小红书": ["{period_word}创作建议1", "{period_word}创作建议2"],
    "视频号": ["{period_word}创作建议1", "{period_word}创作建议2"],
    "抖音": ["{period_word}创作建议1"]
  }},
  "topic_clusters": [
    {{"name": "话题名称", "count": 5, "heat": 90, "representative_title": "代表文章标题"}}
  ],
  "action_items": [
    {{"title": "建议选题", "angle": "切入角度（30字内）", "difficulty": "简单/中等/困难", "platform": "推荐平台"}}
  ]
}}

要求：
- trends 给出 {trend_count} 个{period_word}内容趋势，momentum 为 up/down/stable
- top_picks 从上面数据中选 {picks_count} 个最值得写的选题，按推荐度排序
- top_picks.source_idx 必须是上方数据中对应选题的序号（1-based），后端据此回链原文；source_title 必须逐字复制该序号对应的原文标题，不要改写或翻译
- top_picks.title 是你可以改写的观点化标题，source_title 是原文标题的精确引用，两者分开
- 不要编造 source_url，URL 由后端注入
- top_picks.reason 必须是中文摘要式推荐理由：先概括这条内容讲了什么，再说明为什么值得写；不要输出英文、不要营销夸张词、不要只写"建议关注/可以写"
- category_summary 按分类统计{period_word}内容（count=数量, avg_score=平均创作分, top_title=该分类最热内容）
- platform_tips 给出各平台{period_word}的创作建议（每平台2-3条）
- topic_clusters 识别 {cluster_count} 个热门话题聚类
- action_items 给出 {action_count} 个可执行的创作建议，difficulty 为简单/中等/困难
{period_note}- 所有文本用中文
- 只输出 JSON，不要其他内容"""


# ── Factory helpers ────────────────────────────────────────────


def build_weekly_digest_prompt(
    week_label: str,
    items_text: str,
    category_text: str,
) -> str:
    """Format the digest prompt for weekly use."""
    from app.utils.prompt_safety import sanitize_prompt_input

    return DIGEST_PROMPT.format(
        digest_type="周刊",
        period_label=sanitize_prompt_input(week_label, max_chars=50),
        period_word="本周",
        items_text=sanitize_prompt_input(items_text, max_chars=8000),
        category_text=sanitize_prompt_input(category_text, max_chars=2000),
        overview_limit=300,
        trend_count="3-5",
        picks_count="8-10",
        cluster_count="3-6",
        action_count="5-8",
        reason_limit=60,
        trend_desc_limit=50,
        period_note="",
    )


def build_monthly_digest_prompt(
    month_label: str,
    items_text: str,
    category_text: str,
) -> str:
    """Format the digest prompt for monthly use."""
    from app.utils.prompt_safety import sanitize_prompt_input

    return DIGEST_PROMPT.format(
        digest_type="月刊",
        period_label=sanitize_prompt_input(month_label, max_chars=50),
        period_word="本月",
        items_text=sanitize_prompt_input(items_text, max_chars=8000),
        category_text=sanitize_prompt_input(category_text, max_chars=2000),
        overview_limit=350,
        trend_count="4-6",
        picks_count="10-12",
        cluster_count="4-8",
        action_count="6-10",
        reason_limit=70,
        trend_desc_limit=60,
        period_note="- 明确体现月度复盘，不要写成日报或周报\n",
    )
