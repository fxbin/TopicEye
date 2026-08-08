"""
Creation prompts — extracted from app.services.creation.

Used by:
    - app.services.creation.generate_creation_plan          (快速模式)
    - app.services.creation_explore.generate_explore_directions (探索模式-探索期)
    - app.services.creation_explore.generate_focus_questions    (探索模式-聚焦期)
    - app.services.creation_explore.generate_converge_plan      (探索模式-收敛期)
"""

# ── 探索模式：三段式衰减式脚手架提示词 ──────────────────────────────

EXPLORE_PROMPT = """我是一条待创作的素材，请帮我发现自己看不到的角度。

你的任务分三步：
1. 找出当前素材所属领域中，最常被默认但从未被质疑的3个假设。
2. 对每个假设提出一个"如果反过来会怎样"的挑战。
3. 基于每个挑战生成一个创作方向，标注：独特价值是什么、最容易掉进什么陷阱。

自检规则：
- 如果3个方向全是已有模式的延伸（关键词与素材高度重合），重新生成。
- 方向之间必须互不相同，不能是同一角度的换皮。

防幻觉规则：
- 所有假设和方向必须基于下方素材内容派生，不能凭空编造。
- 如果素材信息不足以支撑3个方向，就少输出，不要硬凑。

素材标题：{title}
素材来源：{source_name}
素材摘要：{summary}
核心观点：{key_points}
标签：{tags}
创作角度（已有）：{creator_angles}

只输出JSON，不要其他内容：
{{
  "assumptions": [
    {{
      "assumption": "",
      "challenge": "",
      "direction": "",
      "unique_value": "",
      "pitfall": ""
    }}
  ]
}}"""


FOCUS_PROMPT = """用户已从探索期的方向中选择了一个。你的任务是逐轮追问，帮用户把模糊的直觉变成可操作的方案。

规则：
- 每轮只问一个维度的问题，等用户回答后再追问下一个。
- 允许用户拒绝你的问题方向并自行重定向——如果用户说"方向不对"，换一个维度问。
- 不要替用户回答，只提问。
- 当用户能用一句话说清楚要做什么时，进入收敛期。

追问维度顺序：
1. 目标受众：具体是谁？他们在什么场景下会看这个内容？
2. 核心冲突：这个内容要解决的矛盾或痛点是什么？
3. 差异化：与已有同类内容相比，独特在哪？

用户选择的方向：{selected_direction}
方向的独特价值：{unique_value}
方向的陷阱：{pitfall}
素材摘要：{summary}
素材核心观点：{key_points}

只输出JSON：
{{
  "question": "",
  "dimension": "audience|conflict|differentiation",
  "round": 1,
  "can_converge": false,
  "reason": ""
}}"""


CONVERGE_PROMPT = """基于前面的探索和追问对话，输出结构化创作方案。

规则：
- 每个关键决策必须标注置信度（high/medium/low）和理由。
- 标注的假设中，必须区分"已验证"和"待验证"。待验证>60%时标注风险提示。
- 标题要基于素材中的核心实体或数字，不得凭空拔高。
- 所有文本用中文。

平台：{platform_name}
用户选择的方向：{selected_direction}
用户回答的追问：{focus_answers}
素材标题：{title}
素材摘要：{summary}
素材核心观点：{key_points}

输出JSON格式：
{{
  "titles": [""],
  "platform_structure": {{
    "hook": "",
    "body": [""],
    "cta": ""
  }},
  "decisions": [
    {{
      "decision": "",
      "confidence": "high|medium|low",
      "reason": ""
    }}
  ],
  "assumptions_status": [
    {{
      "assumption": "",
      "status": "verified|unverified",
      "evidence": ""
    }}
  ],
  "risk_warning": "",
  "tone": "",
  "self_evaluation": {{
    "structure_score": <0-100, 方案结构完整性：标题/hook/正文/结尾是否齐备且逻辑连贯>,
    "executability_score": <0-100, 可执行性：用户拿到方案后能否直接开始创作，还是需要大量补充>,
    "differentiation_score": <0-100, 差异化：与同类内容的已有角度相比是否有新意>,
    "overall_score": <0-100, 综合质量分 = structure*0.3 + executability*0.35 + differentiation*0.35>,
    "warnings": ["具体问题1", "具体问题2"]
  }}
}}"""


# ── 快速模式：平台一次性生成提示词 ──────────────────────────────
# 注意：以下 instruction 是原始字符串，不经过 .format()。
# JSON 大括号用单 {} 是有意的——模型需要看到正确的 JSON 示例。
# 如需在这些模板中使用 .format() 变量替换，必须先把所有 { 替换为 {{、} 替换为 }}。

PLATFORM_PROMPTS = {
    "xiaohongshu": {
        "name": "小红书图文",
        "instruction": """你是一个小红书爆款内容策划师。基于以下素材，生成小红书图文创作方案。

要求：
- 标题：3个备选，用数字/对比/悬念吸引点击，≤20字
- 封面文案：1句核心slogan，≤15字
- 正文结构：开头hook(1句话抓注意力) + 3-5个要点(每个要点含emoji+一句话) + 结尾互动引导
- 话题标签：5-8个热门标签
- 风格要求：口语化、有情绪共鸣、适当用emoji但不过度

输出JSON格式：
{
  "titles": [""],
  "cover_slogan": "",
  "structure": {
    "hook": "",
    "points": [""],
    "cta": ""
  },
  "tags": [""],
  "tone": "",
  "self_evaluation": {
    "structure_score": <0-100, 结构完整性>,
    "executability_score": <0-100, 可执行性>,
    "differentiation_score": <0-100, 差异化>,
    "overall_score": <0-100, 综合=structure*0.3+executability*0.35+differentiation*0.35>,
    "warnings": [""]
  }
}""",
    },
    "short_video": {
        "name": "短视频脚本",
        "instruction": """你是一个短视频脚本策划师。基于以下素材，生成60秒短视频脚本。

要求：
- 标题：3个备选，适合抖音/B站，≤25字
- 开头3秒hook：用冲突/悬念/数据一句话留住观众
- 正文：分3-4个镜头，每个镜头包含画面描述+旁白文案
- 结尾：互动引导(点赞/关注/评论)
- 时长分配：每个镜头标注建议秒数

输出JSON格式：
{
  "titles": [""],
  "total_seconds": 60,
  "scenes": [
    {
      "seq": 1,
      "seconds": 3,
      "visual": "",
      "narration": ""
    }
  ],
  "hook": "",
  "cta": "",
  "bgm_suggestion": "",
  "self_evaluation": {
    "structure_score": <0-100, 结构完整性>,
    "executability_score": <0-100, 可执行性>,
    "differentiation_score": <0-100, 差异化>,
    "overall_score": <0-100, 综合=structure*0.3+executability*0.35+differentiation*0.35>,
    "warnings": [""]
  }
}""",
    },
    "wechat": {
        "name": "公众号长文",
        "instruction": """你是一个公众号爆款文章策划师。基于以下素材，生成公众号长文大纲。

要求：
- 标题：3个备选，适合公众号，可适当长一点但≤30字
- 结构：5-7个小节，每节含标题+核心论点+支撑素材(数据/案例/引用)
- 开头：用故事/数据/痛点引入
- 结尾：金句总结+行动号召
- 适合插入的配图位置标注

输出JSON格式：
{
  "titles": [""],
  "outline": [
    {
      "section": 1,
      "heading": "",
      "points": [""],
      "evidence": "",
      "image_hint": ""
    }
  ],
  "opening": "",
  "closing": "",
  "word_count_estimate": 2000,
  "key_quote": "",
  "self_evaluation": {
    "structure_score": <0-100, 结构完整性>,
    "executability_score": <0-100, 可执行性>,
    "differentiation_score": <0-100, 差异化>,
    "overall_score": <0-100, 综合=structure*0.3+executability*0.35+differentiation*0.35>,
    "warnings": [""]
  }
}""",
    },
}
