"""恢复 changelog 丢失的 product_updates 版本记录数据（issue #182）

Revision ID: e8b1d4f7a2c9
Revises: d2b7f9a41c05
Create Date: 2026-11-01

教训（2026-08 迁移合并事故）：
- product_updates 的数据历来靠 alembic 种子迁移写入。2026-08 迁移合并（2dad8d5）
  删除了全部种子迁移文件，squash 后的 baseline（c003bd551911）只建表不含数据，
  导致之后任何全新初始化的库（含线上重建）changelog 全空。
- 今后迁移合并必须保留种子数据，或像本迁移一样用幂等 seed 迁移承接；
  不得只搬表结构不搬数据。
- 新的版本记录走管理后台「发版记录」录入（POST/PATCH/DELETE
  /product-feedback/updates），数据在库，不再新增种子迁移。

数据口径：按合并前种子迁移链重放的最终态，忠实还原种子内容——
- a9c2f4e1b7d3（one_record 基底）: v0.1.0–v0.5.0 共 8 条（v0.4.0/v0.5.0 为 planned）；
- b2c3d4e5f6a7: v0.5.0 items 追加 OAuth 路线图项（1→2 条）；
- 0a1b2c3d4e5f / 1b2c3d4e5f6a / 2c3d4e5f6a7b: v0.6.0 由计划态覆盖为发布态，
  临时停放的 v0.6.1 记录被 replace 迁移删除——故最终态不含 v0.6.1；
- 5a6b7c8d9e0f / 7b8c9d0e1f2a / s4e5f6g7h8i9: v0.7.0 / v0.8.0 / v0.9.0；
- 3d4e5f6a7b8c（移除 v0.5.0 被推迟项）在纯种子重放下无对象，不影响本数据；
- v0.6.0–v0.9.0 原种子以 NOW() 写 shipped_at，此处取各种子迁移的 Create Date
  定值（与各自发版 commit 日期一致）；
- 历史上 v0.4.0/v0.5.0 曾经管理后台在库里标记为 shipped（无迁移痕迹、
  备份里已是空表，不可恢复），本迁移按种子状态恢复为 planned；
  如需修正状态或补充 items，走管理后台，不再改迁移。

幂等：version 列无唯一约束（仅普通索引 ix_product_updates_version），
不能使用 INSERT ... ON CONFLICT；upgrade 先查现存 version 集合，
只补插缺失的版本。downgrade 按 version 精确删除，不 truncate 全表，
不影响其它版本或人工录入的记录。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "e8b1d4f7a2c9"
down_revision: str | None = "d2b7f9a41c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _e(title: str, description: str, kind: str) -> dict:
    """一条 update entry，与种子迁移的 {title, description, kind} 结构一致。"""
    return {"title": title, "description": description, "kind": kind}


# ── 最终态种子：v0.1.0→v0.9.0 共 12 条（v0.6.1 为临时记录，最终态不含） ──────
SEED_RECORDS: list[dict] = [
    {
        "version": "v0.1.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 5, 22, tzinfo=UTC),
        "created_at": datetime(2026, 5, 22, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 22, tzinfo=UTC),
        "items": [
            _e(
                "全栈项目初始化",
                "FastAPI + Next.js + SQLAlchemy + DuckDB；项目骨架、Repository 层、调度器、全局异常处理。",
                "release",
            ),
            _e(
                "AI 日报",
                "每日基于内容池生成日报；支持历史按日期查询；推送通知。",
                "release",
            ),
            _e(
                "多维信号评分引擎",
                "实现质量/热度/相关性/反馈四维评分；今日精选按 curation_score 排序；支持忽略/不感兴趣。",
                "release",
            ),
            _e(
                "首页筛选 + 精选分可视化",
                "首页支持 sort_by/cate/source 筛选；精选分柱状图组件；忽略按钮 + 类型扩展。",
                "improvement",
            ),
            _e(
                "AI 分析（中英文差异化 prompt）",
                "分析服务按内容语言选不同 prompt；摘要 + 角度 + 选题建议一体输出。",
                "improvement",
            ),
            _e(
                "LLM 实时分类",
                "动态分类创建 + 关键词降级兜底；分类可在运行时由 LLM 扩展。",
                "improvement",
            ),
            _e(
                "收藏夹（localStorage 持久化）",
                "前端 favorites 通过 localStorage 跨会话保留；强化类型安全，移除 as any 绕过。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.1.1",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 5, 26, tzinfo=UTC),
        "created_at": datetime(2026, 5, 26, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 26, tzinfo=UTC),
        "items": [
            _e(
                "多热榜数据源",
                "新增知乎热榜、抖音热榜、Reddit 爬虫；扩展现有 RSS/RSSHub 通用抓取层。",
                "release",
            ),
            _e(
                "数据统计仪表盘",
                "新增 /stats Tab：内容总览 + 信源/分类分布 + 时间趋势 + 网文统计；DuckDB 聚合查询。",
                "release",
            ),
            _e(
                "信源级别采集频率控制",
                "每个 source 可独立配置 fetch_interval_minutes；调度器按各 source 的间隔分桶调度。",
                "improvement",
            ),
            _e(
                "低粉爆文发现",
                "新增 low_follower_viral 算法：在低粉丝信源中识别异常热度信号。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.1.2",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 5, 29, tzinfo=UTC),
        "created_at": datetime(2026, 5, 29, tzinfo=UTC),
        "updated_at": datetime(2026, 5, 29, tzinfo=UTC),
        "items": [
            _e(
                "网文雷达：番茄 + 七猫 + 知乎盐选",
                "新增三大网文平台榜单抓取：番茄走 fanqienovel.com API、七猫走 Playwright + Nuxt 解析、知乎盐选走 api.zhihu.com 公开端点。",
                "release",
            ),
            _e(
                "用户反馈机制",
                "用户可对单条内容点赞/点踩，反馈进入算法评分修正。",
                "release",
            ),
            _e(
                "日报/周刊通知推送",
                "日报和周刊生成后通过通知中心推送；前端有未读小红点。",
                "improvement",
            ),
            _e(
                "评分流程诊断",
                "新增 algorithm 评分流程诊断端点，暴露每条内容的评分拆解（质量/热度/相关性/反馈）。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.2.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 6, 6, tzinfo=UTC),
        "created_at": datetime(2026, 6, 6, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 6, tzinfo=UTC),
        "items": [
            _e(
                "AI 分析队列并发化",
                "同步进入的新选题自动进入后台分析队列，减少 pending 堆积并提升整体吞吐；批量分析接口使用并发执行，内容增强批处理也并发化。",
                "release",
            ),
            _e(
                "反馈信号进入算法闭环",
                "用户反馈汇总为评分修正信号，回流到今日精选、摘要候选和算法解释链路。",
                "improvement",
            ),
            _e(
                "网文周报 + 网文雷达原文入口",
                "新增 webnovel 报告服务，按周聚合各平台数据；网文雷达支持点击进入作品详情。",
                "release",
            ),
            _e(
                "计划与权益关联",
                "plans 模型与用户当前权益绑定，为后续 Pro 付费墙做准备。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.2.1",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 6, 8, tzinfo=UTC),
        "created_at": datetime(2026, 6, 8, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 8, tzinfo=UTC),
        "items": [
            _e(
                "反馈与更新工作台",
                "新增 /product-feedback 端点：用户可匿名提交产品问题，管理员可查看/分类/标记修复；前端新增反馈中心页（更新记录 + 问题列表）。",
                "release",
            ),
            _e(
                "匿名问题反馈",
                "未登录用户也可以提交产品问题，后台可以统一查看、处理并标记已修复。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.3.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 6, 14, tzinfo=UTC),
        "created_at": datetime(2026, 6, 14, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 14, tzinfo=UTC),
        "items": [
            _e(
                "公共/私有信源双层模型",
                "sources 加 owner_user_id 字段，系统公共信源与用户私有信源隔离；新增 /sources/me 系列端点（GET/POST/PUT/DELETE/sync）；内容列表与详情按归属做可见性过滤。",
                "release",
            ),
            _e(
                "用户专属日报",
                "daily_reports 加归属字段，/daily-reports/me 端点拉用户私有日报；调度器按用户循环生成，并发控制避免 timeout。",
                "release",
            ),
            _e(
                "信源类型扩展：YouTube / Podcast / Newsletter",
                "新增 YouTube、Podcast (RSS) 与 Newsletter 抓取器；创建信源时粘贴 URL 自动识别类型，降低私有信源接入门槛。",
                "improvement",
            ),
            _e(
                "网文榜单接入：黑岩 + 点众",
                "黑岩走 biz.zhangwenpindu.cn 公开 CDN API，点众走 _next/data SSG 接口；均无需登录即可抓取书城首页 + 男女频排行榜。",
                "improvement",
            ),
            _e(
                "DuckDB 趋势 top_items JSON 反序列化",
                "PG 端 JSON 列返回字符串、DuckDB 视图读为 string，两条链路都需要 json.loads 后才能送前端；统一在持久化层解码。",
                "fix",
            ),
            _e(
                "trends 边界 NaN 修复",
                "话题趋势分位数截断在边界条件下产生 NaN，导致前端展示为空；改为整数截断并增加守卫。",
                "fix",
            ),
        ],
    },
    {
        "version": "v0.4.0",
        "status": "planned",
        "target_date": date(2026, 9, 30),
        "shipped_at": None,
        "created_at": datetime(2026, 6, 14, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 14, tzinfo=UTC),
        "items": [
            _e(
                "算法准确性回归看板",
                "继续补齐候选、分析、反馈、摘要之间的验证闭环；当前已在 scoring_flow 接入 feedback_signal，看板 UI 与跨切面回放待补。",
                "roadmap",
            ),
            _e(
                "支付与订阅（先 Stripe）",
                "抽象 PaymentGateway 协议，先接 Stripe 海外（订阅 + webhook + 客户门户），稳后再加微信/支付宝。订阅数据模型：subscriptions / payment_events / invoices；plan_catalog 改结构化数值。",
                "roadmap",
            ),
        ],
    },
    {
        "version": "v0.5.0",
        "status": "planned",
        "target_date": date(2026, 12, 31),
        "shipped_at": None,
        "created_at": datetime(2026, 6, 14, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 14, tzinfo=UTC),
        "items": [
            _e(
                "多用户配额与规模化",
                "LLM 配额按 user_id 分桶（Redis token bucket）；进程内状态外移到 Redis / PG（auth 限流 / LLM 缓存 / job 锁）；认证限流改按用户。触发条件：北极星指标趋势 + 反指标健康。",
                "roadmap",
            ),
            # OAuth 项由 b2c3d4e5f6a7 追加进 v0.5.0 items
            _e(
                "OAuth 登录与开源准备",
                "接入 Google / GitHub OAuth 登录（Authlib），新增 user_oauth_accounts 关联表与自动合并策略（已验证邮箱自动关联，未验证邮箱拒绝以防劫持）；password_hash 改 nullable 支持纯 OAuth 用户；前端登录页加第三方登录按钮与回调消费页（token 走 URL fragment）。为项目开源化铺路。",
                "roadmap",
            ),
        ],
    },
    {
        # 最终态来自 2c3d4e5f6a7b（replace）：v0.6.0 = 发布态，4 条 items
        "version": "v0.6.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 7, 14, 18, 30, tzinfo=UTC),
        "created_at": datetime(2026, 7, 14, 18, 30, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 14, 18, 30, tzinfo=UTC),
        "items": [
            _e(
                "站内原文阅读",
                "内容卡片现可进入站内阅读：优先使用已采集正文，否则按安全边界读取公开网页；始终保留来源跳转，不渲染第三方 HTML。",
                "release",
            ),
            _e(
                "长文阅读排版优化",
                "正文快照保留标题、段落、引用和列表；阅读页改为单一阅读纸与更舒适的行长、行距，旧快照也会自动切段。",
                "improvement",
            ),
            _e(
                "精选可见性与缓存口径修正",
                "精选、低粉爆文和内容列表统一遵循公共内容加本人私有内容的可见性范围，并按用户隔离相关缓存。",
                "fix",
            ),
            _e(
                "站内阅读结果观测",
                "记录读取成功、缓存命中、失败原因与耗时，为后续只向高价值来源引入 JS 渲染能力提供数据依据。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.7.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        "created_at": datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 18, 10, 0, tzinfo=UTC),
        "items": [
            _e(
                "统计仪表盘可视化升级",
                "分类分布改为分层组合（概览条 + Top10 表 + 蓝海卡），突出低量高分的蓝海分类；长尾分类可折叠，避免被头部分类压扁。",
                "improvement",
            ),
            _e(
                "统计接口性能优化",
                "隔离缓存失效域、延长 TTL、加骨架屏，解决统计接口在高数据量下响应慢的问题。",
                "improvement",
            ),
            _e(
                "后端基础设施收敛",
                "抽取 SQLite 事务重试、admin 校验、HTTP 重试、digest 基类等公共 helper；清理 digest/time/get_db/config/_post_sync_pipeline 等兼容 re-export 层；统一时间获取与数据库会话入口，降低重复度。",
                "improvement",
            ),
            _e(
                "前端公共组件体系",
                "抽取 Surface/PanelTitle/StatTile/Pagination/FieldLabel 等公共组件，统一 CHART_COLORS/Tone/LEVEL_CONFIG 设计 token；today-picks 等页面拆分展示组件、数据获取与静态配置。",
                "improvement",
            ),
            _e(
                "阅读器翻译快照查询修复",
                "translate_snapshot 改按 content_id 查询而非主键 id，修复翻译缓存命中错误快照的问题。",
                "fix",
            ),
        ],
    },
    {
        "version": "v0.8.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 7, 19, 11, 0, tzinfo=UTC),
        "created_at": datetime(2026, 7, 19, 11, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 19, 11, 0, tzinfo=UTC),
        "items": [
            _e(
                "母题 per-user 化：系统模板库 + 用户 fork",
                "母题从全局共享改为多租户模型。admin 维护系统模板库（owner_user_id IS NULL，所有用户只读）；普通用户首次访问「我的母题」时自动 fork 一份系统模板到自己名下，之后可自由调整关键词、权重和目标读者，改动立即影响打分队列。",
                "release",
            ),
            _e(
                "新增「母题配置」用户页 /my-topics/config",
                "普通用户可在 /my-topics/config 管理自己的母题：新建、编辑、停用、fork 系统模板。系统模板标记为只读，引导用户 fork 后个性化。原有 /admin/mother-topics 定位调整为「系统母题模板库」。",
                "release",
            ),
            _e(
                "打分接口 per-user 隔离",
                "score / score-batch / match 接口按「系统模板 + 当前用户的 fork」过滤母题，确保用户修改母题后打分结果立即生效，不再被全局共享的 admin 配置覆盖。",
                "improvement",
            ),
        ],
    },
    {
        "version": "v0.9.0",
        "status": "shipped",
        "target_date": None,
        "shipped_at": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        "created_at": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        "items": [
            _e(
                "跨源证据与可信线索体系",
                "新增跨源证据系统（模型 + 服务 + API），支持信源画像管理、证据链详情与批量查询；可信线索标注与效果验证埋点，独立看板页面展示验证结果；增强内容搜索至跨字段模糊匹配，信源溯源由 SourceBadge 组件统一呈现。",
                "release",
            ),
            _e(
                "内容关联发现系统",
                "建立内容关联模型与规则引擎（causal / response / contrast 三类），聚类任务自动调用关联发现，LLM 补充语义级关联；前端 AnalysisPanel 集成关联内容展示与力导向图可视化（SVG force simulation）。",
                "release",
            ),
            _e(
                "内容事件治理",
                "建立内容事件真源与增量归一化机制，统一事件证据与精选口径；新增内容事件审核工作台与审核 API，支持事件归并依据展示、同事件消息折叠、主消息附属内容聚合；Webhook 推送日志历史与管理页面。",
                "release",
            ),
            _e(
                "微信读书阅读统计增强",
                "书架视图支持排序 / 分组 / 划线预览 / 统计图表（状态环形图、进度直方图、Top10 条形图）；新增阅读统计 MVP（完成率漏斗、笔记密度散点、阅读脉搏、暂停标记）；接入阅读统计 / 热门划线 / 完整书架三个 Gateway API；页面拆分为三 Tab 布局，缓存持久化。",
                "release",
            ),
            _e(
                "个性化推荐与 Prompt 管理",
                "新增个性化推荐兴趣向量服务，今日精选集成个性化排序与行为触发；Prompt 注册表同步与管理 API，评分反馈看板 API 与前端管理页面；创作方案 AI 自评嵌入生成流程，前端展示自评面板。",
                "release",
            ),
            _e(
                "可观测性监控大盘",
                "内置 Prometheus 指标采集与监控大盘，支持可配置刷新、日志面板与进程指标；指标快照持久化与日志环形缓冲；LLM 调用链路增加内存指标采集，模型池运行指标导出。",
                "release",
            ),
            _e(
                "站内阅读与通知推送增强",
                "Reader 支持 PDF 原文站内阅读，curl_cffi TLS 指纹模拟降级；日报 / 周报 / 月报选题接入站内阅读 ReaderDrawer 并注入 content_id；新增报告阅读时长上报与过期清理；通知推送支持多 webhook 配置、卡片消息格式、事件类型开关与发送测试。",
                "improvement",
            ),
            _e(
                "全 Docker 化生产部署",
                "提供完整 Docker Compose 生产部署方案，支持 SQLite 或 PostgreSQL 后端、OAuth 登录（Google / GitHub）、Nginx 反向代理，数据归用户所有。",
                "release",
            ),
            _e(
                "安全与工程质量加固",
                "加密模型渠道凭据，收紧前端响应安全默认项；api/v1 分层违规机器检查接入 CI，ORM 查询全面下沉到 repositories 层；ruff lint 告警清零（437 自动修复 + 57 手动修复）；弹窗键盘无障碍与交互控件可访问性语义强化。",
                "improvement",
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
    # 按 version 精确删除（含历史重复行），不动其它版本记录。
    for version in SEED_VERSIONS:
        bind.execute(
            sa.text("DELETE FROM product_updates WHERE version = :version"),
            {"version": version},
        )
