"""
母题初始化种子脚本。
创建规划中定义的四个母题及其关键词。
"""

from __future__ import annotations

import logging
from sqlalchemy import select
from app.core.database import async_session
from app.models.mother_topic import MotherTopic, ContentType

logger = logging.getLogger(__name__)

MOTHER_TOPICS = [
    {
        "name": "写作/记录",
        "description": "写作的意义、记录的意义、人生小记、个人知识库",
        "keywords": [
            # 写作核心词
            "写作",
            "写作的意义",
            "记录",
            "记录的意义",
            "写下来",
            "文字表达",
            "表达自己",
            "开始写",
            "动笔",
            "写作习惯",
            "持续写作",
            "每天写",
            "写作打卡",
            "日更",
            "写作困境",
            # 个人知识库
            "个人知识库",
            "知识管理",
            "笔记系统",
            "卡片盒",
            "卢曼",
            "Obsidian",
            "Notion",
            "双链笔记",
            "知识沉淀",
            "知识整理",
            "写作素材",
            "素材库",
            "灵感记录",
            "写作素材积累",
            # 人生小记
            "人生小记",
            "日常记录",
            "生活记录",
            "复盘",
            "周记",
            "月度总结",
            "年度复盘",
            "写日记",
            "日记",
            "手帐",
        ],
        "weight": 1.0,
        "content_type": ContentType.PERSONAL.value,
        "target_reader": "愿意通过写作整理生活、沉淀思考的人",
        "display_order": 1,
    },
    {
        "name": "AI/工具/时代观察",
        "description": "AI工具更新、工作流、编码工具、Agent/Memory/Knowledge",
        "keywords": [
            # AI工具
            "AI工具",
            "ChatGPT",
            "Claude",
            "Copilot",
            "GPT-4",
            "AI助手",
            "大模型",
            "LLM",
            "GPT",
            "DeepSeek",
            "Kimi",
            "通义千问",
            "文心一言",
            "AI软件",
            "AI应用",
            "AI产品",
            "AI写作",
            "AI绘画",
            "AI编程",
            "AI搜索",
            # 工作流
            "工作流",
            "效率工具",
            "效率提升",
            "生产力工具",
            "工作提效",
            "自动化工作流",
            "工作方式",
            "效率方法",
            "省时间",
            "Notion",
            "Raycast",
            "Alfred",
            "Shortcuts",
            "IFTTT",
            "工作流自动化",
            "流程优化",
            "效率优化",
            # 编码工具
            "编码工具",
            "编程工具",
            "IDE",
            "VSCode",
            "Cursor",
            "AI编程",
            "Copilot",
            "代码生成",
            "代码助手",
            "开发工具",
            "程序员工具",
            "程序员效率",
            "写代码",
            "编程效率",
            # Agent/Memory/Knowledge
            "Agent",
            "AI Agent",
            "智能体",
            "记忆",
            "Memory",
            "知识库",
            "RAG",
            "知识管理",
            "个人知识库",
            "AI知识库",
            "向量数据库",
            "Embedding",
            "上下文",
            "上下文窗口",
            # 时代观察
            "AI时代",
            "人工智能时代",
            "技术变革",
            "AI改变",
            "AI影响",
            "未来趋势",
            "AI趋势",
            "技术趋势",
            "行业变化",
            "职业变化",
        ],
        "weight": 1.0,
        "content_type": ContentType.TOOL_REVIEW.value,
        "target_reader": "对AI工具和效率提升有兴趣的创作者和知识工作者",
        "display_order": 2,
    },
    {
        "name": "努力/成长",
        "description": "长期主义、学习与积累、自我塑造",
        "keywords": [
            # 长期主义
            "长期主义",
            "长期坚持",
            "长期投入",
            "长期主义思维",
            "积累",
            "复利",
            "复利效应",
            "时间复利",
            "慢慢来",
            "坚持",
            "持续",
            "持续努力",
            "不放弃",
            "韧性",
            "耐心",
            "耐心等待",
            "延迟满足",
            "延迟享受",
            # 学习与积累
            "学习",
            "学习方法",
            "学习效率",
            "学习能力",
            "学会学习",
            "知识积累",
            "技能积累",
            "认知积累",
            "经验积累",
            "成长",
            "个人成长",
            "认知成长",
            "能力成长",
            "成长记录",
            "进步",
            "持续进步",
            "小步快跑",
            "迭代",
            "自我迭代",
            "刻意练习",
            "一万小时",
            "专家",
            "领域专家",
            # 自我塑造
            "自我塑造",
            "塑造自己",
            "成为自己",
            "自我突破",
            "突破舒适区",
            "走出舒适区",
            "挑战自己",
            "自我超越",
            "改变自己",
            "自我提升",
            "自我进化",
            "自我完善",
            "习惯养成",
            "好习惯",
            "坏习惯",
            "培养习惯",
            "戒掉坏习惯",
            "自律",
            "自驱",
            "内驱力",
            "主动性",
            "目标感",
        ],
        "weight": 1.0,
        "content_type": ContentType.METHODOLOGY.value,
        "target_reader": "相信长期积累力量的年轻人",
        "display_order": 3,
    },
    {
        "name": "生活/自我",
        "description": "成为自己、日常观察、普通人的生活判断",
        "keywords": [
            # 成为自己
            "成为自己",
            "做自己",
            "真实自己",
            "自我认同",
            "接纳自己",
            "自我接纳",
            "爱自己",
            "善待自己",
            "不讨好",
            "不迎合",
            "自我价值",
            "自我认知",
            "认识自己",
            "了解自己",
            "自我探索",
            "人生选择",
            "选择自己",
            "活出自己",
            "真实生活",
            # 日常观察
            "日常观察",
            "生活观察",
            "观察生活",
            "生活感悟",
            "日常感悟",
            "生活碎片",
            "生活细节",
            "细节观察",
            "小事情",
            "小事",
            "生活灵感",
            "生活思考",
            "生活哲学",
            "生活美学",
            # 普通人的生活判断
            "普通人",
            "普通人的生活",
            "平凡生活",
            "平凡人",
            "普通人视角",
            "真实生活",
            "真实故事",
            "普通人故事",
            "生活记录",
            "生活判断",
            "生活选择",
            "日常决定",
            "生活决策",
            "幸福感",
            "小确幸",
            "生活满足感",
            "简单生活",
            "极简生活",
            "内心平静",
            "情绪管理",
            "心态",
            "积极心态",
            "好心态",
        ],
        "weight": 1.0,
        "content_type": ContentType.OBSERVATION.value,
        "target_reader": "在日常生活中寻找意义的普通人",
        "display_order": 4,
    },
]


async def seed_mother_topics() -> int:
    """创建或更新四个母题（幂等）。"""
    added = 0
    async with async_session() as db:
        for topic_data in MOTHER_TOPICS:
            # 检查是否已存在
            result = await db.execute(select(MotherTopic).where(MotherTopic.name == topic_data["name"]))
            existing = result.scalar_one_or_none()

            if existing:
                # 更新关键词（确保最新）
                existing.keywords = topic_data["keywords"]
                existing.description = topic_data["description"]
                existing.weight = topic_data["weight"]
                existing.content_type = topic_data["content_type"]
                existing.target_reader = topic_data["target_reader"]
                existing.display_order = topic_data["display_order"]
                logger.info("Updated: %s", topic_data["name"])
            else:
                topic = MotherTopic(
                    name=topic_data["name"],
                    description=topic_data["description"],
                    keywords=topic_data["keywords"],
                    weight=topic_data["weight"],
                    content_type=topic_data["content_type"],
                    target_reader=topic_data["target_reader"],
                    is_active=True,
                    display_order=topic_data["display_order"],
                )
                db.add(topic)
                added += 1
                logger.info("Created: %s", topic_data["name"])

        await db.commit()
        return added


if __name__ == "__main__":
    import asyncio

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    async def main():
        added = await seed_mother_topics()
        print(f"母题初始化完成: 新增 {added} 条")

    asyncio.run(main())
