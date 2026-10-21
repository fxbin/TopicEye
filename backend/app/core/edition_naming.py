"""刊物种属词族（后端镜像）——全站唯一真相源在 frontend/src/lib/edition-naming.ts。

#132（命名圆桌 2026-10-20 定稿「情报正族」）：公式 [时间/范围]+情报。

组串两模板：
- 报头眉题（前端渲染）：只放种属词，品牌由主标题「选题雷达」承担
- 单走场景（推送卡片/邮件主题等无报头主标题的场合）：edition_title(key)
  =「选题雷达 · {种属}」双段拼，品牌在场

本模块与前端镜像的一致性由 scripts/check_edition_naming.py 对账锁定
（模式同 check_scoring_mirror.py），改词必须两边同步改。
"""

from __future__ import annotations

from datetime import date

EDITION_LABELS: dict[str, str] = {
    "daily": "今日情报",
    # 日期中性形式：历史期/快照期出刊用（报头支持 ?date= 深链历史期，
    # 「今日情报」配历史日期会自相矛盾——圆桌 ns 未覆盖的边界，#132 复审补）
    "daily_neutral": "每日情报",
    "weekly": "每周情报",
    "monthly": "每月情报",
    # 特刊预留位：特刊产品化时启用
    "special": "专题情报",
}


def edition_title(key: str) -> str:
    """单走场景组串：品牌在场。"""
    return f"选题雷达 · {EDITION_LABELS[key]}"


def daily_edition_label(report_date: str | None = None) -> str:
    """日报种属：当日出刊「今日情报」，历史/快照期「每日情报」（同族中性形式）。"""
    if report_date:
        try:
            today = date.today().isoformat()
            if str(report_date) == today:
                return EDITION_LABELS["daily"]
        except (TypeError, ValueError):
            pass
    return EDITION_LABELS["daily_neutral"]


def daily_edition_title(report_date: str | None = None) -> str:
    """日报单走组串（品牌在场），随当日/历史切换种属。"""
    return f"选题雷达 · {daily_edition_label(report_date)}"


def daily_generation_notice(report_date: str | None = None) -> str:
    """日报生成完成通知标题，随当日/历史切换种属。"""
    return f"{daily_edition_label(report_date)}生成完成"
