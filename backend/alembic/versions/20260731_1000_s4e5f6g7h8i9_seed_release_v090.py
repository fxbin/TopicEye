"""seed release v0.9.0

Revision ID: s4e5f6g7h8i9
Revises: q3e4f5g6h7i8
Create Date: 2026-07-31 10:00:00.000000

发布 v0.9.0：跨源证据与可信线索体系、内容关联发现系统、内容事件治理、
微信读书阅读统计增强、个性化推荐与 Prompt 管理、可观测性监控大盘、
站内阅读与通知推送增强、全 Docker 化生产部署、安全与工程质量加固。
"""

from __future__ import annotations

import json

from alembic import op
import sqlalchemy as sa


revision = "s4e5f6g7h8i9"
down_revision = "q3e4f5g6h7i8"
branch_labels = None
depends_on = None


_VERSION = "v0.9.0"
_ITEMS = [
    {
        "title": "跨源证据与可信线索体系",
        "description": "新增跨源证据系统（模型 + 服务 + API），支持信源画像管理、证据链详情与批量查询；可信线索标注与效果验证埋点，独立看板页面展示验证结果；增强内容搜索至跨字段模糊匹配，信源溯源由 SourceBadge 组件统一呈现。",
        "kind": "release",
    },
    {
        "title": "内容关联发现系统",
        "description": "建立内容关联模型与规则引擎（causal / response / contrast 三类），聚类任务自动调用关联发现，LLM 补充语义级关联；前端 AnalysisPanel 集成关联内容展示与力导向图可视化（SVG force simulation）。",
        "kind": "release",
    },
    {
        "title": "内容事件治理",
        "description": "建立内容事件真源与增量归一化机制，统一事件证据与精选口径；新增内容事件审核工作台与审核 API，支持事件归并依据展示、同事件消息折叠、主消息附属内容聚合；Webhook 推送日志历史与管理页面。",
        "kind": "release",
    },
    {
        "title": "微信读书阅读统计增强",
        "description": "书架视图支持排序 / 分组 / 划线预览 / 统计图表（状态环形图、进度直方图、Top10 条形图）；新增阅读统计 MVP（完成率漏斗、笔记密度散点、阅读脉搏、暂停标记）；接入阅读统计 / 热门划线 / 完整书架三个 Gateway API；页面拆分为三 Tab 布局，缓存持久化。",
        "kind": "release",
    },
    {
        "title": "个性化推荐与 Prompt 管理",
        "description": "新增个性化推荐兴趣向量服务，今日精选集成个性化排序与行为触发；Prompt 注册表同步与管理 API，评分反馈看板 API 与前端管理页面；创作方案 AI 自评嵌入生成流程，前端展示自评面板。",
        "kind": "release",
    },
    {
        "title": "可观测性监控大盘",
        "description": "内置 Prometheus 指标采集与监控大盘，支持可配置刷新、日志面板与进程指标；指标快照持久化与日志环形缓冲；LLM 调用链路增加内存指标采集，模型池运行指标导出。",
        "kind": "release",
    },
    {
        "title": "站内阅读与通知推送增强",
        "description": "Reader 支持 PDF 原文站内阅读，curl_cffi TLS 指纹模拟降级；日报 / 周报 / 月报选题接入站内阅读 ReaderDrawer 并注入 content_id；新增报告阅读时长上报与过期清理；通知推送支持多 webhook 配置、卡片消息格式、事件类型开关与发送测试。",
        "kind": "improvement",
    },
    {
        "title": "全 Docker 化生产部署",
        "description": "提供完整 Docker Compose 生产部署方案，支持 SQLite 或 PostgreSQL 后端、OAuth 登录（Google / GitHub）、Nginx 反向代理，数据归用户所有。",
        "kind": "release",
    },
    {
        "title": "安全与工程质量加固",
        "description": "加密模型渠道凭据，收紧前端响应安全默认项；api/v1 分层违规机器检查接入 CI，ORM 查询全面下沉到 repositories 层；ruff lint 告警清零（437 自动修复 + 57 手动修复）；弹窗键盘无障碍与交互控件可访问性语义强化。",
        "kind": "improvement",
    },
]


def upgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text("SELECT id FROM product_updates WHERE version = :version"),
        {"version": _VERSION},
    ).fetchone()
    if exists is not None:
        return

    now_sql = "CURRENT_TIMESTAMP" if bind.dialect.name == "sqlite" else "NOW()"
    items_sql = ":items" if bind.dialect.name == "sqlite" else "CAST(:items AS JSON)"
    bind.execute(
        sa.text(
            f"""
            INSERT INTO product_updates (version, status, shipped_at, items, created_at, updated_at)
            VALUES (:version, :status, {now_sql}, {items_sql}, {now_sql}, {now_sql})
            """
        ),
        {
            "version": _VERSION,
            "status": "shipped",
            "items": json.dumps(_ITEMS, ensure_ascii=False),
        },
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text("DELETE FROM product_updates WHERE version = :version"), {"version": _VERSION})
