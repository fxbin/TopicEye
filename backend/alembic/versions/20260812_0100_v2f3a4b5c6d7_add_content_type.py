"""add content_type column to content_items for dual-axis classification

Revision ID: v2f3a4b5c6d7
Revises: u1f2a3b4c5d6
Create Date: 2026-08-12 01:00:00

新增 content_type 列，实现双轴分类：
  - category: 主题轴（AI / 科技 / 产品 / ...）
  - content_type: 形态轴（论文 / 技术 / 资讯 / 教程 / ...）

数据回填策略：
  1. 从 source.category 的 `/` 分隔符解析（如 "AI/论文" -> content_type="论文"）
     解析后经 _CONTENT_TYPE_ALIASES 标准化，与摄入链路（classifier._normalize_content_type）保持一致
  2. arXiv 平台硬规则回填 content_type="论文"

纯增量操作：加列 + 加索引 + 数据回填，无删除/变更已有列。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "v2f3a4b5c6d7"
down_revision = "u1f2a3b4c5d6"
branch_labels = None
depends_on = None


# ── 形态别名 -> 标准化 content_type ─────────────────────────────────
# 必须与 app/services/classifier.py 的 _CONTENT_TYPE_ALIASES 保持一致。
# 否则迁移回填的原始值（如 "paper"）与摄入链路写入的标准化值（"论文"）
# 不一致，会导致前端按中文标准值筛选时遗漏存量数据。
_CONTENT_TYPE_ALIASES: dict[str, str] = {
    "论文": "论文", "paper": "论文", "学术": "论文",
    "技术": "技术", "tech": "技术",
    "资讯": "资讯", "新闻": "资讯", "news": "资讯",
    "教程": "教程", "tutorial": "教程", "指南": "教程",
    "观点": "观点", "评论": "观点", "opinion": "观点",
    "工具": "工具", "tool": "工具", "产品": "工具",
    "体验": "体验", "review": "体验", "测评": "体验",
    "成长": "成长", "思维": "成长",
    "讨论": "讨论", "discussion": "讨论",
    "项目": "项目", "project": "项目", "开源": "项目",
}


def _normalize_content_type(raw: str) -> str | None:
    """与 classifier._normalize_content_type 等价的标准化逻辑。"""
    key = raw.strip().lower()
    if not key:
        return None
    return _CONTENT_TYPE_ALIASES.get(key) or raw.strip()[:50]


def upgrade() -> None:
    op.add_column(
        "content_items",
        sa.Column("content_type", sa.String(50), nullable=True),
    )

    # ── Backfill 1: 从 source.category 的 `/` 分隔符解析 ──────────────
    # 使用 Python 逐行回填，兼容 PostgreSQL 和 SQLite
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, category FROM sources WHERE category LIKE '%/%'")
    ).fetchall()
    for source_id, category in rows:
        parts = str(category).split("/", 1)
        if len(parts) == 2:
            content_type = _normalize_content_type(parts[1])
            if content_type:
                conn.execute(
                    sa.text(
                        "UPDATE content_items SET content_type = :ct "
                        "WHERE source_id = :sid AND content_type IS NULL"
                    ),
                    {"ct": content_type, "sid": source_id},
                )

    # ── Backfill 2: arXiv 平台硬规则 ──────────────────────────────────
    conn.execute(
        sa.text(
            "UPDATE content_items SET content_type = '论文' "
            "WHERE platform = 'arXiv' AND content_type IS NULL"
        )
    )

    op.create_index(
        "ix_content_items_content_type",
        "content_items",
        ["content_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_items_content_type", table_name="content_items")
    op.drop_column("content_items", "content_type")
