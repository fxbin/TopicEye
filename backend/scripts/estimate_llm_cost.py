#!/usr/bin/env python
"""
Token cost estimation for LLM analysis calls.

NOT a pytest test — this script makes real API calls to measure token usage
and estimate monthly costs. Run manually:
    python scripts/estimate_llm_cost.py
"""

import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.chdir(os.path.join(os.path.dirname(__file__), ".."))

import asyncio
from openai import AsyncOpenAI
from dotenv import load_dotenv

load_dotenv()

SYSTEM_PROMPT = """你是一位资深内容策展分析师，负责评估内容的选题价值并决定是否入选精选。

你的评分标准参考了一线内容策展平台的精选规则：
- 信息密度（纯转发/一句话感想直接淘汰）
- 可操作性（能直接上手用的工具/教程得分更高）
- 相关性（必须和目标领域直接相关）
- 来源权威度（一手信源 > 二手转载）
- 时效性（首发/独家 > 已被广泛报道）

所有评分范围 0-100。所有文本使用中文。语气直接、有态度、不说客套话。"""

ANALYSIS_PROMPT = """请对以下内容进行完整分析。

标题：{title}
正文：{content}

请严格按以下 JSON 格式输出（不要输出任何其他内容）：
{{
  "summary": "一句话摘要（30字以内）",
  "key_points": ["核心观点1", "核心观点2", "核心观点3"],
  "tags": ["标签1", "标签2"],
  "scores": {{
    "quality_score": <0-100, 信息密度和逻辑性>,
    "hot_score": <0-100, 当前热度和传播速度>,
    "freshness_score": <0-100, 新鲜度和时效性>,
    "creator_score": <0-100, 对创作者的选题价值>,
    "viral_score": <0-100, 爆文传播潜力>,
    "risk_score": <0-100, 内容风险>
  }},
  "curation": {{
    "info_density": <0-100, 信息密度：纯转发/空话=0-20, 有观点=40-60, 有数据/案例/方法=70-100>,
    "actionability": <0-100, 可操作性：纯资讯=10-30, 有参考价值=40-60, 能直接上手用=70-100>,
    "source_weight": <0-100, 来源权威度：匿名/营销号=10-30, 二手转载=40-60, 一手信源/官方/KOL=70-100>,
    "curation_score": <0-100, 综合精选分（加权：信息密度30%+可操作性25%+创作者价值20%+爆文潜力15%+来源10%，风险分>70则扣20分）>
  }},
  "recommendation": "精选推荐理由（30字以内，口语化，有态度，带行动建议。例：'中转站掺水终于有人做了可审计检测，用API的立刻装上测一测'）",
  "creator_angles": ["创作角度1", "创作角度2", "创作角度3"],
  "title_suggestions": ["建议标题1", "建议标题2", "建议标题3"]
}}

精选分（curation_score）评判标准：
- ≥80：重大发布/独家/强实用性工具/高传播力事件
- 70-79：扎实的产品更新/行业动态/有价值教程
- 60-69：有参考价值但不够突出
- <60：信息量低/纯情绪/重复内容/过于个人化

精选门槛为 60 分。"""

# Simulate a real content item (~500 chars, typical RSS article)
fake_content = """AI算力需求暴增导致全球光纤产能紧张，多家运营商报告交货期从8周延长至20周以上。分析机构预测这一趋势将持续至2026年底。光纤供应商股价全线上涨，其中长飞光纤光缆股份有限公司股价在本周内上涨超过15%。

据行业分析师介绍，AI数据中心的建设速度远超预期，每个大型AI训练集群需要数千公里的光纤连接。这种需求增长速度是传统电信网络建设时期的3-4倍。

全球主要光纤制造商包括康宁、长飞光纤、普睿司曼等均已满负荷运转，但仍无法满足订单需求。部分运营商已开始提前6个月下单以确保供应。

分析师指出，这一趋势对光纤产业链上下游都将产生深远影响，从光纤预制棒到光模块厂商都可能受益。投资者可关注相关产业链标的。"""


async def test():
    client = AsyncOpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    )
    resp = await client.chat.completions.create(
        model="deepseek-v4-flash",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": ANALYSIS_PROMPT.format(
                    title="AI数据中心致光纤价格暴涨，交货期限延长至20周以上",
                    content=fake_content,
                ),
            },
        ],
        temperature=0.25,
        max_tokens=1500,
    )
    u = resp.usage
    print("=== Real Analysis Token Usage ===")
    print(f"prompt_tokens: {u.prompt_tokens}")
    print(f"completion_tokens: {u.completion_tokens}")
    print(f"total_tokens: {u.total_tokens}")
    if hasattr(u, "prompt_cache_hit_tokens"):
        print(f"cache_hit: {u.prompt_cache_hit_tokens}")
    if hasattr(u, "prompt_cache_miss_tokens"):
        print(f"cache_miss: {u.prompt_cache_miss_tokens}")

    # DeepSeek V4 Flash pricing (RMB per million tokens)
    # Input (cache miss): 1 元/M
    # Input (cache hit): 0.02 元/M
    # Output: 2 元/M
    input_miss = (u.prompt_tokens or 0) * 1 / 1_000_000
    output = (u.completion_tokens or 0) * 2 / 1_000_000
    print("\n=== Cost Per Analysis Call ===")
    print(f"Input cost: {input_miss:.6f} 元")
    print(f"Output cost: {output:.6f} 元")
    print(f"Total: {input_miss + output:.6f} 元")

    # Project monthly cost
    print("\n=== Monthly Projection ===")
    for daily_items in [50, 100, 200]:
        cost = (input_miss + output) * daily_items * 30
        print(f"  {daily_items}条/天 × 30天 = {daily_items * 30}次/月 → {cost:.2f} 元/月")


if __name__ == "__main__":
    asyncio.run(test())
