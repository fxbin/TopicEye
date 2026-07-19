"""merge source types: WECHAT/XIAOHONGSHU/BILIBILI → RSSHub, CUSTOM → WEBSITE

Revision ID: 8c9d0e1f2a3b
Revises: 7b8c9d0e1f2a
Create Date: 2026-07-19 14:00:00.000000

合并信源类型枚举：
  公众号  → RSSHub (platform='微信公众号')
  小红书  → RSSHub (platform='小红书')
  B站     → RSSHub (platform='B站')
  自定义  → 网站

这三个类型原本就没有独立 scraper，实际抓取全部走 RSSHub 路由；
"自定义"与"网站"共用同一个 WebsiteScraper。合并后枚举从 16 → 12。
source_type 列底层为 VARCHAR，无需变更列类型，仅做数据迁移。
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "8c9d0e1f2a3b"
down_revision = "7b8c9d0e1f2a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 公众号 / 小红书 / B站 → RSSHub，保留原平台信息
    op.execute(
        sa.text(
            "UPDATE sources SET source_type = 'RSSHub', "
            "platform = COALESCE(platform, '微信公众号') "
            "WHERE source_type = '公众号'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE sources SET source_type = 'RSSHub', "
            "platform = COALESCE(platform, '小红书') "
            "WHERE source_type = '小红书'"
        )
    )
    op.execute(
        sa.text(
            "UPDATE sources SET source_type = 'RSSHub', "
            "platform = COALESCE(platform, 'B站') "
            "WHERE source_type = 'B站'"
        )
    )
    # 自定义 → 网站
    op.execute(
        sa.text(
            "UPDATE sources SET source_type = '网站' "
            "WHERE source_type = '自定义'"
        )
    )


def downgrade() -> None:
    # 无法无损还原 platform → source_type 的映射（RSSHub 信源不一定来自这三个平台）
    # 仅回滚"自定义 → 网站"
    op.execute(
        sa.text(
            "UPDATE sources SET source_type = '自定义' "
            "WHERE source_type = '网站' AND platform IS NULL"
        )
    )
