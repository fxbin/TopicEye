"""补录 v0.9.0 之后缺失的 product_updates 版本记录（issue #182 续）

Revision ID: f2c8e6a4b9d1
Revises: e8b1d4f7a2c9
Create Date: 2026-11-01

背景：v0.9.0（2026-07-31）之后版本记录长期未补——历史数据一直靠种子迁移
写入，管理后台「发版记录」上线后录入流程断档：既没人走后台录入，也没有
再落种子迁移，changelog 停留在 v0.9.0 长达三个版本。

本次按 git 历史补录 v0.10.0–v0.13.0 四个版本（条目为发版定稿的编辑稿，
kind 按语义映射到 ProductUpdateKind 枚举值：新能力=release、增强=improvement、
缺陷修复=fix）。今后新版本一律走管理后台「发版记录」录入
（POST/PATCH/DELETE /product-feedback/updates），不再新增种子迁移。

shipped_at 口径——发版代表 commit 的 committer date（git show -s
--format=%cI，+08:00 换算 UTC）：
- v0.10.0 ← 70e3a86（feat(scoring) 六维评分四档行为锚点 #115）2026-10-12；
- v0.11.0 ← 841177a（feat(naming) 刊族口径收尾 #135）2026-10-21；
- v0.12.0 ← 86d2480（feat(ingest) 掘金全文入库 #161）2026-10-27；
- v0.13.0 当日发布，取 2026-11-01。
created_at/updated_at 与 shipped_at 同日（tzinfo=UTC）。

幂等：与 e8b1d4f7a2c9 相同——version 列无唯一约束（仅普通索引），不能用
ON CONFLICT；upgrade 先查现存 version 集合，只补插缺失的版本。downgrade
只按 version 精确删除本迁移补录的 4 条，不动 e8b1d4f7a2c9 恢复的前 12 条
及其它版本的人工记录（迁移对这 4 个 version 字符串拥有所有权）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "f2c8e6a4b9d1"
down_revision: str | None = "e8b1d4f7a2c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _e(title: str, description: str, kind: str) -> dict:
    """一条 update entry，与种子迁移的 {title, description, kind} 结构一致。"""
    return {"title": title, "description": description, "kind": kind}


# ── 补录种子：v0.10.0→v0.13.0 共 4 条 ──────────────────────────────────────
SEED_RECORDS: list[dict] = [
    # 「选题引擎可观测与校准」
    {
        "version": "v0.10.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 10, 12, 15, 58, tzinfo=UTC),
        "created_at": datetime(2026, 10, 12, 15, 58, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 12, 15, 58, tzinfo=UTC),
        "items": [
            _e(
                "六维评分加四档行为锚点",
                "中英文用同一把尺子，并附对照跑分工具。",
                "release",
            ),
            _e(
                "SelectBench v0",
                "双引擎对照矩阵与金标校准工具链。",
                "release",
            ),
            _e(
                "降级内容自动补分析",
                "日报场景豁免预算限制。",
                "improvement",
            ),
            _e(
                "LLM 调用三窗预算熔断",
                "超支自动刹车。",
                "improvement",
            ),
            _e(
                "第三方登录改为管理后台网页配置",
                "登录方式不用再改代码，在管理后台网页里直接增改。",
                "improvement",
            ),
            _e(
                "邮件通知只保留自定义 SMTP",
                "下线 Brevo。",
                "improvement",
            ),
        ],
    },
    # 「情报产品与开放接口」
    {
        "version": "v0.11.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 10, 21, 15, 56, 9, tzinfo=UTC),
        "created_at": datetime(2026, 10, 21, 15, 56, 9, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 21, 15, 56, 9, tzinfo=UTC),
        "items": [
            _e(
                "日报、周刊全面改版",
                "晨报、周刊、特刊三种产品形态。",
                "release",
            ),
            _e(
                "刊物命名统一为「情报正族」",
                "今日情报等八处口径合一。",
                "improvement",
            ),
            _e(
                "MCP 服务器上线",
                "经 /mcp 用 Bearer token 直连选题雷达。",
                "release",
            ),
            _e(
                "MCP 动态 OAuth 授权",
                "浏览器弹窗登录、同意页、回跳。",
                "release",
            ),
            _e(
                "管理后台重设计",
                "四组导航、五个界面原语、七页换壳。",
                "improvement",
            ),
            _e(
                "闲置 OAuth 客户端自动清理与授权记录保护",
                "长期不用的客户端自动清掉，已授权的记录不会被误删。",
                "improvement",
            ),
        ],
    },
    # 「事件归并与阅读体验」
    {
        "version": "v0.12.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 10, 27, 9, 1, 53, tzinfo=UTC),
        "created_at": datetime(2026, 10, 27, 9, 1, 53, tzinfo=UTC),
        "updated_at": datetime(2026, 10, 27, 9, 1, 53, tzinfo=UTC),
        "items": [
            _e(
                "同一事件的多篇报道自动归并",
                "卡片内可展开其它报道。",
                "release",
            ),
            _e(
                "事件候选池完整召回与响应回放评估",
                "调用用量关联预算。",
                "improvement",
            ),
            _e(
                "内容导入提速",
                "分片入库、批量聚类写回，导入不再超时。",
                "improvement",
            ),
            _e(
                "纯链接内容准入",
                "标题取自原文，无正文也可入库参与精选。",
                "release",
            ),
            _e(
                "掘金等信源入库前抓取全文保存",
                "站内阅读不再跳出。",
                "improvement",
            ),
            _e(
                "反爬站点识别与冷却",
                "抓取失败不再反复外呼。",
                "improvement",
            ),
        ],
    },
    # 「竞品雷达四连发与安全清零」
    {
        "version": "v0.13.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 11, 1, tzinfo=UTC),
        "created_at": datetime(2026, 11, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 1, tzinfo=UTC),
        "items": [
            _e(
                "AI 分析同一事件的报道",
                "提示还没人写的角度和受众在问的问题。",
                "release",
            ),
            _e(
                "支持按关键词、信源、域名隐藏不想看的内容",
                "在个人中心设置静音规则，信息流和今日精选不再出现命中内容。",
                "release",
            ),
            _e(
                "热榜条目标注所处阶段",
                "发酵、爆发、回落、常青。",
                "release",
            ),
            _e(
                "发布前检测文稿里的违禁词和广告法极限词",
                "粘贴文稿即可检测，按分类和严重程度高亮，并给替换建议。",
                "release",
            ),
            _e(
                "模型配置改版",
                "卡片信息分级，添加模型改为选渠道、选模型、填密钥。",
                "improvement",
            ),
            _e(
                "依赖安全升级",
                "authlib、litellm、msgpack、pypdf 已知漏洞清零。",
                "fix",
            ),
        ],
    },
]

SEED_VERSIONS = tuple(r["version"] for r in SEED_RECORDS)


def upgrade() -> None:
    bind = op.get_bind()

    # version 无唯一约束，不能用 ON CONFLICT：先查现存 version，只补缺失的。
    existing = {row[0] for row in bind.execute(sa.text("SELECT DISTINCT version FROM product_updates"))}
    missing = [r for r in SEED_RECORDS if r["version"] not in existing]
    if not missing:
        return

    product_updates = sa.table(
        "product_updates",
        sa.column("version", sa.String),
        sa.column("status", sa.String),
        sa.column("target_date", sa.Date),
        sa.column("shipped_at", sa.DateTime(timezone=True)),
        sa.column("items", sa.JSON),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(product_updates, missing)


def downgrade() -> None:
    bind = op.get_bind()
    # 按 version 精确删除（含历史重复行），不动前 12 条种子及其它版本记录。
    for version in SEED_VERSIONS:
        bind.execute(
            sa.text("DELETE FROM product_updates WHERE version = :version"),
            {"version": version},
        )
