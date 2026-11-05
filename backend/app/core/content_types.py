"""分类与评分共用的内容形态；主题 category 与形态 content_type 正交。"""

# ── 内容形态（双轴分类的 format 轴） ────────────────────────────────
# 与 category（主题轴）正交，描述内容的呈现形态/意图
CONTENT_TYPES: list[str] = [
    "论文",  # 学术论文 / 预印本
    "技术",  # 技术文章 / 工程实践
    "资讯",  # 新闻 / 行业动态
    "教程",  # 教程 / 指南 / How-to
    "观点",  # 评论 / 分析 / 观点
    "工具",  # 工具 / 产品发布
    "体验",  # 体验测评 / 用户研究
    "成长",  # 个人成长 / 思维方法
    "讨论",  # 社区讨论 / 问答
    "项目",  # 开源项目 / Side Project
]

# 信源 category 中 `/` 后的形态别名 -> 标准化 content_type
CONTENT_TYPE_ALIASES: dict[str, str] = {
    "论文": "论文",
    "paper": "论文",
    "学术": "论文",
    "技术": "技术",
    "tech": "技术",
    "资讯": "资讯",
    "新闻": "资讯",
    "news": "资讯",
    "教程": "教程",
    "tutorial": "教程",
    "指南": "教程",
    "观点": "观点",
    "评论": "观点",
    "opinion": "观点",
    "工具": "工具",
    "tool": "工具",
    "产品": "工具",
    "体验": "体验",
    "review": "体验",
    "测评": "体验",
    "成长": "成长",
    "思维": "成长",
    "讨论": "讨论",
    "discussion": "讨论",
    "项目": "项目",
    "project": "项目",
    "开源": "项目",
}


def normalize_content_type(value: str | None) -> str | None:
    """兼容既有分类合同：规范已知别名，未知形态截断后透传。"""
    if not value:
        return None
    key = str(value).strip().lower()
    if not key:
        return None
    return CONTENT_TYPE_ALIASES.get(key, str(value).strip()[:50])
