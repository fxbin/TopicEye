# TopicEye — 创作者选题雷达

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![CI](https://github.com/fxbin/TopicEye/actions/workflows/ci.yml/badge.svg)](https://github.com/fxbin/TopicEye/actions/workflows/ci.yml)
[![Backend: FastAPI](https://img.shields.io/badge/Backend-FastAPI-009688.svg)](https://fastapi.tiangolo.com/)
[![Frontend: Next.js](https://img.shields.io/badge/Frontend-Next.js_16-black.svg)](https://nextjs.org/)

[English](README.md) | [简体中文](README.zh-CN.md)

---

AI 驱动的内容发现与选题分析平台。TopicEye 持续抓取 25+ 信源（RSS / Reddit / YouTube / 播客 / Newsletter / 热榜），用一套透明的 6 维评分引擎给每条内容打分，把今天真正值得写的话题推到你面前。为被信息噪音淹没的内容创作者而做——不是又一个 RSS 阅读器。

![今日选题](docs/screenshots/screenshot-today.png)

## 核心特性

- **透明的评分引擎，不是黑盒。** 每条精选内容都带完整评分拆解：基础分（信息密度 / 可操作性 / 创作者价值 / 爆文潜力 / 来源权威 / 时效新鲜）、质量门槛、时效衰减、多样性惩罚、反馈信号。
- **反馈闭环校准。** 你的 👍 / 👎 不只是被收藏——它以 15% 权重回灌进排序权重，引擎越用越准。
- **多源情报。** 25+ 抓取信源（RSS / Reddit / YouTube / 播客 / Newsletter / 热榜）+ 微信读书阅读统计 + 网文雷达（番茄 / 七猫 / 知乎盐选）。一个平台，全频段信号。
- **支持自部署。** 完整 Docker 方案，SQLite 或 PostgreSQL，OAuth 登录（Google / GitHub）。数据归你所有。
- **Agent-native（规划中）。** 评分引擎正在以稳定 API 形式开放，让别的 Agent / 工具可以把它作为排序层调用。

## 截图

### 核心发现

| 今日选题 | 日报 | 趋势雷达 |
|---|---|---|
| ![today](docs/screenshots/screenshot-today.png) | ![daily](docs/screenshots/screenshot-daily.png) | ![trending](docs/screenshots/screenshot-trending.png) |

| 趋势追踪 | 低粉爆文 | 算法流程 |
|---|---|---|
| ![trends](docs/screenshots/screenshot-trends.png) | ![lfv](docs/screenshots/screenshot-low-follower-viral.png) | ![algorithm](docs/screenshots/screenshot-algorithm.png) |

### 数据统计与报告

| 数据统计 | 任务统计 | 更新记录 |
|---|---|---|
| ![stats](docs/screenshots/screenshot-stats.png) | ![stats-jobs](docs/screenshots/screenshot-stats-jobs.png) | ![changelog](docs/screenshots/screenshot-changelog.png) |

| 周报 | 月报 | |
|---|---|---|
| ![weekly](docs/screenshots/screenshot-weekly.png) | ![monthly](docs/screenshots/screenshot-monthly.png) | |

### 新功能 — 微信读书 & 网文雷达

| 微信读书统计 | 网文雷达 |
|---|---|
| ![weread](docs/screenshots/screenshot-weread.png) | ![novel](docs/screenshots/screenshot-novel.png) |

### 用户工作台

| 收藏夹 | 我的选题 | 选题配置 |
|---|---|---|
| ![favorites](docs/screenshots/screenshot-favorites.png) | ![my-topics](docs/screenshots/screenshot-my-topics.png) | ![my-topics-config](docs/screenshots/screenshot-my-topics-config.png) |

| 登录 | 个人资料 | |
|---|---|---|
| ![login](docs/screenshots/screenshot-login.png) | ![profile](docs/screenshots/screenshot-profile.png) | |

### 后台管理

| 管理概览 | 信源管理 | 内容管理 |
|---|---|---|
| ![admin](docs/screenshots/screenshot-admin.png) | ![admin-sources](docs/screenshots/screenshot-admin-sources.png) | ![admin-contents](docs/screenshots/screenshot-admin-contents.png) |

| 用户管理 | AI 引擎 | 母题模板库 |
|---|---|---|
| ![admin-users](docs/screenshots/screenshot-admin-users.png) | ![admin-model-eval](docs/screenshots/screenshot-admin-model-eval.png) | ![admin-mother-topics](docs/screenshots/screenshot-admin-mother-topics.png) |

| 发版记录 | 反馈工作台 | 系统设置 |
|---|---|---|
| ![admin-updates](docs/screenshots/screenshot-admin-updates.png) | ![admin-feedback](docs/screenshots/screenshot-admin-feedback.png) | ![admin-settings](docs/screenshots/screenshot-admin-settings.png) |

## 功能模块

| 模块 | 说明 |
|------|------|
| 信源管理 | RSS / RSSHub / Reddit / YouTube / 播客 / Newsletter / 自定义网站。公共信源 + 用户私有信源双层模型。 |
| 内容精选 | 6 维 LLM 评分引擎 + 百分位截断 (P70) + 风险控制 + 用户反馈校准 |
| AI 分析 | 每条内容的摘要 / 关键点 / 选题建议（中英文差异化 prompt） |
| 日报 / 周报 / 月报 | 自动从内容池生成，支持时间线视图与历史滚动浏览 |
| 趋势雷达 | 关键词热度追踪 + 低粉爆文发现（在爆之前找到它） |
| 微信读书 | 对接微信读书官方 gateway，同步阅读统计与书架数据；每日自动刷新缓存，阅读时长分析与书架对比 |
| 网文雷达 | 番茄 / 七猫 / 知乎盐选热榜，受运行时功能开关控制，默认关闭 |
| 母题模板 | 多租户模型——管理员维护系统模板库（只读），用户首次访问时自动 fork 一份到自己名下，可自定义关键词、权重、目标读者。修改立即影响打分队列。 |
| AI 模型评测 | 后台 UI 对比多个 LLM 在同一 prompt 下的表现，追踪质量与成本，为不同任务选合适的路由组。 |
| 邮件验证 | 事务邮件支持 Brevo API 或任意 SMTP（QQ 企业邮 / Gmail 等），在管理后台设置页配置。 |
| 站内阅读 | 对原文链接的站内阅读器——仅抓取公开 HTML，不使用登录态 / Cookie / 验证码 / 反爬绕过，带 SSRF 防护与快照缓存。 |
| 收藏夹 | 跨会话保存感兴趣的内容（按用户隔离） |
| 我的选题 | 个性化选题配置，支持母题 fork、关键词过滤、评分覆盖 |
| 后台管理 | 完整管理界面：信源、内容、用户、AI 模型评测、母题模板、发版记录、反馈、系统设置 |
| OAuth 登录 | Google / GitHub（也支持邮箱密码） |
| 速率限制 | 登录、注册、LLM 调用按端点配额限流 |

## 架构

### 后端分层

严格单向依赖（完整规则见 [AGENTS.md](AGENTS.md)）：

```text
api/v1/ ──► services/ ──► repositories/ ──► models/ ──► sqlalchemy
```

| 层 | 职责 | 禁止 |
|---|---|---|
| `api/v1/` | 路由声明、请求校验、响应组装 | `import sqlalchemy`（`AsyncSession` 类型注解除外）、直接写 ORM 查询 |
| `services/` | 业务编排、事务边界、跨 repo 组合 | 无 |
| `repositories/` | ORM 唯一入口，CRUD + 复杂查询封装 | 互相 import、写业务逻辑 |
| `models/` | 纯 ORM 声明、字段定义、`__table_args__` | 业务方法、副作用、IO |
| `schemas/` | Pydantic 请求/响应模型、序列化 | ORM import、DB 访问 |

跨层支撑：`core/`（配置、DB、日志、retry）、`middleware/`（限流、请求指标）、`services/email/`（Brevo + SMTP）、`services/llm/`（failover / 熔断 / 响应缓存）、`services/scrapers/` + `services/trending_scrapers/`（按信源的抓取器）。

### 评分引擎

6 维基础分（权重和为 1.0）：

| 维度 | 权重 | 衡量什么 |
|---|---|---|
| 信息密度 | 0.25 | 内容的信噪比 |
| 可操作性 | 0.20 | 读者今天能不能拿这个去做事 |
| 创作者价值 | 0.18 | 对写这个话题的人有多大用 |
| 爆文潜力 | 0.15 | 破圈的可能性 |
| 来源权威 | 0.12 | 来源的可信度权重 |
| 时效新鲜 | 0.10 | 时间衰减（`exp(-0.02 × 小时)`，下限 0.3） |

后处理：

- **质量门槛** — 低于 45 视为太薄；高于 70 完全信任。
- **风险控制** — 风险分 >82 硬排除；>45 起开始软降级。
- **多样性惩罚** — 同源重复 ×0.85，同类重复 ×0.92（有 grace 槽位）。
- **百分位截断** — 选取 P70 及以上（约前 30%）。
- **反馈信号** — 👍 / 👎 以 15% 权重计入，单条上下限 ±20，防止单条投票主导排序。
- **最低入选分** — 基础分最低 58 才能入选；批次整体偏弱时引擎不会硬塞弱内容。

完整配置见 [backend/app/services/scoring_engine.py](backend/app/services/scoring_engine.py)。

### 信源矩阵

| 类别 | 信源 |
|---|---|
| RSS / RSSHub | 任意 RSS、RSSHub 路由（自定义站点、博客订阅） |
| 聚合器 | Reddit、Hacker News、GitHub Trending、V2EX、掘金、少数派、IT之家、36Kr |
| 社交 / 短视频 | 微博、抖音（热榜 + 上升榜）、哔哩哔哩、贴吧、知乎热榜 |
| 财经 | 雪球、东方财富、网易财经、搜狐财经 |
| 发现 | 豆瓣、虎扑、黑岩、爱书柜、Xyzrank、今日头条、百度 |
| 长内容 | YouTube、播客、Newsletter |
| 阅读 | 微信读书（阅读统计 + 书架，走官方 gateway） |
| 网文 | 番茄、七猫、知乎盐选（运行时功能开关，默认关闭） |

### 数据库选型

- **SQLite** — 本地 / 单用户部署默认。零运维，单文件。写锁等待通过 `SQLITE_BUSY_TIMEOUT_MS` 控制（默认 30s，批量写 500ms 快速返回 503）。
- **PostgreSQL 16** — 多用户 / 生产推荐。CI 在 SQLite + PostgreSQL 上都跑测试套件，提前抓跨 DB 兼容性 bug。
- **DuckDB** — OLTP 之上的只读分析层。支撑统计面板，不污染写路径。内存与线程预算通过 `DUCKDB_THREADS` / `DUCKDB_MEMORY_LIMIT` 调整。

## 技术栈

- **后端：** FastAPI（异步）· SQLAlchemy 2.0 · Alembic · DuckDB（分析层）· httpx
- **前端：** Next.js 16 · React 19 · TypeScript · Tailwind CSS v4
- **数据库：** SQLite（默认）或 PostgreSQL · DuckDB 作为 OLTP 的只读分析层
- **认证：** 不透明 bearer token（DB hash）+ Authlib OAuth
- **邮件：** Brevo API 或 SMTP（按部署自行配置）
- **基础设施：** Docker / docker-compose（dev + prod）· APScheduler

## 快速开始

### 环境要求

- Python 3.12+ · Node.js 20+ · Git
- **或** Docker + Docker Compose（最省事）

### 方式 A — Docker Compose（生产模式，推荐用于部署服务）

使用 [docker-compose.prod.yml](docker-compose.prod.yml)：代码 bake 进镜像，无热重载，带 healthcheck / 资源限制，默认走 Postgres。

```bash
git clone https://github.com/fxbin/TopicEye.git
cd TopicEye
docker compose -f docker-compose.prod.yml up -d --build
```

- 前端：http://localhost:3000
- 后端 API 文档：http://localhost:8000/docs

> 默认的 [docker-compose.yml](docker-compose.yml) 是热重载开发配置（bind mount + `--reload` + `npm run dev`），只用于本地开发，不是部署配置。

### 方式 B — Docker Compose（开发模式，热重载）

```bash
git clone https://github.com/fxbin/TopicEye.git
cd TopicEye
docker compose up -d
```

端口同上。源码改动自动重载。PostgreSQL 通过 `postgres` profile 按需启用：

```bash
docker compose --profile postgres up -d
```

### 方式 C — 本地开发（不用 Docker）

**1. 后端**（端口 8102）

```bash
cd TopicEye/backend
python -m venv venv && source venv/bin/activate
pip install -r requirements-dev.txt   # 含 pytest + pytest-asyncio
cp .env.example .env                  # 按需修改
uvicorn app.main:app --host 127.0.0.1 --port 8102 --reload
```

**2. 前端**（端口 3000，新开终端）

```bash
cd TopicEye/frontend
npm install
npm run dev
```

浏览器打开 http://localhost:3000。若代理未绕过 `127.0.0.1`，设置 `BACKEND_API_URL=http://127.0.0.1:8102 npm run dev`。

> **代理注意：** 如果系统开着 HTTP 代理（ClashX / Surge 端口 7890），确保 `localhost` 和 `127.0.0.1` 在「绕过代理」列表里，或设置 `BACKEND_API_URL=http://127.0.0.1:8102 npm run dev`。
>
> **OAuth 回调 URL：** 本地跑后端在 :8102 时，Google / GitHub OAuth 控制台里的回调地址应填 `http://localhost:8102/api/v1/auth/oauth/{google,github}/callback`；Docker 模式用 `:8000`。

## 配置

全部配置走环境变量，完整列表见 [`backend/.env.example`](backend/.env.example)。关键项：

| 变量 | 默认值 | 用途 |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./topiceye.db` | OLTP 数据库。切 Postgres 用 `postgresql+asyncpg://...` |
| `CORS_ORIGINS` | `http://localhost:3000,...` | 允许的前端来源，逗号分隔 |
| `OAUTH_GOOGLE_CLIENT_ID` / `_SECRET` | 空 | 启用 Google 登录 |
| `OAUTH_GITHUB_CLIENT_ID` / `_SECRET` | 空 | 启用 GitHub 登录 |
| `OAUTH_FRONTEND_REDIRECT_URL` | `http://localhost:3000/oauth/callback` | 前端 OAuth 回调页（token 走 URL fragment） |
| `ADMIN_SEED_ENABLED` | `false` | 设 `true` 并配 `ADMIN_EMAIL` / `ADMIN_PASSWORD`，启动时创建或提升管理员 |
| `AUTH_LOGIN_ATTEMPTS_PER_MINUTE` | `20` | 每 IP 登录速率限制 |
| `LLM_REQUESTS_PER_MINUTE` | `30` | 每用户 LLM 调用速率限制 |
| `RSS_SCRAPER_TIMEOUT_SECONDS` | `15` | 单次 RSS 抓取超时；慢站可在 source 的 `settings` 里覆写 |
| `SOURCE_SYNC_TIMEOUT_SECONDS` | `120` | 单信源整体同步超时 |
| `ARTICLE_READER_ENABLED` | `true` | 站内阅读器开关（仅抓公开 HTML，带 SSRF 防护） |

> **网文雷达模块**（番茄 / 七猫 / 知乎盐选）受运行时功能开关控制，默认关闭。管理员可在 **信源管理 → 功能模块开关** 一键开启，或调 `PUT /api/v1/settings/feature-flags`。无需重启。
>
> **邮件验证** 在管理后台设置页配置，两种 provider：
> - **Brevo API** — 免费版 300 邮件/天，无需信用卡，但需账号审核。
> - **SMTP** — 自带任意 provider（QQ 企业邮 / Gmail 等），无需审核。

## 开发

```bash
# 后端测试（使用隔离的测试库）
cd backend && python -m pytest tests/ -q

# 前端类型检查
cd frontend && npx tsc --noEmit

# 手动触发单个信源抓取
curl -X POST http://127.0.0.1:8102/api/v1/sources/1/sync
```

项目使用 Conventional Commits（`feat(auth): ...`、`fix(cache): ...`）。完整工作流见 [CONTRIBUTING.md](CONTRIBUTING.md)，本仓库强制执行的提交规范与分层规则见 [AGENTS.md](AGENTS.md)。

CI 在每次 push 和 PR 上跑四条 lane：

- **后端测试**：SQLite + PostgreSQL 双 DB（提前抓跨 DB bug——之前一个 INSERT 主键 bug 在 SQLite 测试通过但 PG 生产全挂）。
- **前端类型检查**：`tsc --noEmit`。
- **前端单测 + 覆盖率门禁**：限定在 `src/lib` 纯逻辑模块。
- **Lint**：`ruff` 只检查 PR 中变更的 Python 文件（渐进式，不一次性扫历史）。

## 贡献

欢迎贡献。详见 [CONTRIBUTING.md](CONTRIBUTING.md)（环境搭建、代码风格、工作流）。可以认领带 `good first issue` 标签的 issue 作为入门任务。

## 协议

基于 [Apache License, Version 2.0](LICENSE) 开源。Copyright © 2026 fxbin。
