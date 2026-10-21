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

EDITION_LABELS: dict[str, str] = {
    "daily": "今日情报",
    "weekly": "每周情报",
    "monthly": "每月情报",
    # 特刊预留位：特刊产品化时启用
    "special": "专题情报",
}


def edition_title(key: str) -> str:
    """单走场景组串：品牌在场。"""
    return f"选题雷达 · {EDITION_LABELS[key]}"
