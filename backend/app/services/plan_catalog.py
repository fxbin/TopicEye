from __future__ import annotations

from typing import Any, Optional


PLAN_TIERS: list[dict[str, Any]] = [
    {
        "key": "free",
        "name": "当前免费体验",
        "price_label": "0 元",
        "positioning": "当前已开放的单人创作者工作区，适合先验证选题、复盘和收藏流程。",
        "highlight": "公开浏览 + 登录后个人工作台，自定义 AI 配置需升级付费权益。",
        "features": [
            "公开浏览今日选题、当日精选、低粉爆文和趋势雷达",
            "登录后使用日报、周刊、月刊、数据统计和我的母题",
            "收藏夹、算法流程和网文雷达对登录用户开放",
            "个人中心支持基础集成 API Key 加密保存",
            "自定义 AI Key 和模型配置不对免费用户开放",
            "信源管理、AI 引擎和数据同步仍由管理员维护",
        ],
        "limits": {
            "daily_topic_view": "暂未强制限额",
            "favorites": "按账号隔离",
            "custom_sources": "管理员维护",
            "creation_plans_per_day": "暂未强制限额",
            "team_members": 1,
        },
        "cta": "当前已开放",
        "recommended": False,
    },
    {
        "key": "pro",
        "name": "Pro 规划",
        "price_label": "待定",
        "positioning": "规划给稳定更新的单人创作者，后续用于承接更高额度和更完整的创作流。",
        "highlight": "规划方向：更高额度、个人信源、导出和自动 Brief。",
        "features": [
            "更细的免费/付费功能开关",
            "更高额度的收藏和创作方案生成",
            "普通用户自助配置个人信源和 API 数据源",
            "允许配置个人自定义 AI Key / API Base / 模型路由",
            "更完整的数据分析工作台视图",
            "导出选题库和自动 Brief（规划中）",
        ],
        "limits": {
            "daily_topic_view": "规划：更高额度",
            "favorites": "规划：扩容",
            "custom_sources": "规划：个人可配置",
            "creation_plans_per_day": "规划：更高额度",
            "team_members": 1,
        },
        "cta": "规划 Pro 功能",
        "recommended": True,
    },
    {
        "key": "studio",
        "name": "Studio 规划",
        "price_label": "待定",
        "positioning": "规划给工作室、矩阵号和内容团队，重点是团队协作和批量运营。",
        "highlight": "规划方向：协作、批量信源、队列化同步和可配置数据库。",
        "features": [
            "团队成员和协作看板（规划中）",
            "批量信源导入和同步队列（规划中）",
            "收藏夹与选题库团队共享（规划中）",
            "算法流程可调试配置沉淀（规划中）",
            "SQLite / PostgreSQL 可配置切换，DuckDB 固定作为分析层",
        ],
        "limits": {
            "daily_topic_view": "规划：团队额度",
            "favorites": "规划：团队容量",
            "custom_sources": "规划：批量维护",
            "creation_plans_per_day": "规划：团队额度",
            "team_members": "规划：多人",
        },
        "cta": "规划 Studio 功能",
        "recommended": False,
    },
    {
        "key": "enterprise",
        "name": "企业/私有化规划",
        "price_label": "定制",
        "positioning": "面向垂直行业内容团队和私有化场景，当前只保留规划占位。",
        "highlight": "组织权限、审计、私有部署和外部推送均未正式开放。",
        "features": [
            "私有部署和组织权限（规划中）",
            "审计日志和管理员策略（规划中）",
            "外部 API / Webhook 接入（规划中）",
            "企业微信、飞书等推送（规划中）",
            "行业信源包和专属策略模型（待评估）",
        ],
        "limits": {
            "daily_topic_view": "定制",
            "favorites": "定制",
            "custom_sources": "定制",
            "creation_plans_per_day": "定制",
            "team_members": "定制",
        },
        "cta": "联系定制",
        "recommended": False,
    },
]


FREE_AREA = [
    "公开可看：今日选题、当日精选、低粉爆文、趋势雷达、趋势追踪、权益规划",
    "登录后可用：日报、周刊、月刊、数据统计、我的母题、收藏夹、算法流程、网文雷达",
    "个人中心：账号信息、个人集成 API Key 加密保存",
    "管理员可用：信源管理、AI 引擎、内容/母题配置、网文数据同步",
]


PAID_AREA = [
    "自定义 AI 配置需要付费权益，当前按用户 plan 做后端拦截",
    "后续优先规划：额度边界、个人信源配置、导出、自动 Brief",
    "团队协作、批量同步、组织权限和私有部署仍是规划项",
    "未完成能力只作为路线图展示，不作为当前可用承诺",
]


def get_plan_catalog() -> dict[str, Any]:
    return {
        "tiers": PLAN_TIERS,
        "free_area": FREE_AREA,
        "paid_area": PAID_AREA,
        "currency": "CNY",
        "source": "docs/创作者选题雷达_1_0_prd_融合版.md#商业模式初稿",
    }


def get_tier_by_key(plan_key: str | None) -> dict[str, Any]:
    normalized = (plan_key or "free").strip().lower() or "free"
    return next((tier for tier in PLAN_TIERS if tier["key"] == normalized), PLAN_TIERS[0])


def get_plan_catalog_for_user(plan_key: str | None = None) -> dict[str, Any]:
    catalog = get_plan_catalog()
    current_tier = get_tier_by_key(plan_key)
    return {
        **catalog,
        "current_plan": current_tier["key"],
        "current_tier": current_tier,
    }


def plan_allows_custom_ai(plan_key: str | None) -> bool:
    return get_tier_by_key(plan_key)["key"] in {"pro", "studio", "enterprise"}


def plan_allows_private_source(plan_key: str | None) -> bool:
    """Whether the plan tier permits creating user-owned (private) sources."""
    return get_tier_by_key(plan_key)["key"] in {"pro", "studio", "enterprise"}
