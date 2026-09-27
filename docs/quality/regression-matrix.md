# 质量回归矩阵与缺陷清单（#5）

> 建立日期：2026-09-27（基于 main @ 7203847 的证据核查）；同日独立复核修正了 §一 OAuth 命令、§三 第 1/5 行命令与证据口径、D-5 公告计数口径。
> 本文件是 [Issue #5](https://github.com/fxbin/TopicEye/issues/5) 要求的「单一缺陷/复现矩阵」，后续缺陷与回归条目**只在此追加**，避免散落在聊天记录和 issue 评论里。

## 一、运行安全守则（先读再跑）

后端测试的 conftest 有 autouse `clean_tables` fixture，会对 `DATABASE_URL` 指向的库执行
`TRUNCATE ... CASCADE` 并终止其它连接。**直接对开发库跑 `pytest tests/` 会清空数据。**

| 场景 | 命令 | 说明 |
|---|---|---|
| 后端全量（推荐） | `make test-backend` | 自动起一次性 PG 容器（127.0.0.1:5433，`topiceye_test` 库），跑完即删；可用 `TEST_PG_PORT` 换端口并行 |
| 针对性 PG 测试 | 见下表各条目 | 自建一次性库（`CREATE DATABASE ..._tmp`）后以 `DATABASE_URL` 指向运行，用完 `DROP DATABASE` |
| OAuth 修复隔离测试 | `DATABASE_URL='postgresql+asyncpg://dummy:dummy@localhost:5432/never_connect' uv run --no-sync python -m pytest tests_oauth_patch/` | 全 mock，不连任何数据库；必须 `python -m`（`tests_oauth_patch/` 无 `__init__.py`，裸 `pytest` 解析不到 `app` 包，`tests/` 因是包不受影响） |
| 前端 | `cd frontend && npx tsc --noEmit && npm run test:coverage` | 类型门禁 + 单测/覆盖率 |

## 二、缺陷清单（confirmed defects）

每条按 #5 要求的十个维度登记；复现与修复细节以 issue 正文为准，此处只留索引和当前状态。

### D-1 管理员权限测试泄漏真实 DuckDB attach — #22 ✅ 已修复关闭（2026-09-27）
- **症状**：权限测试通过后，下一个测试在 fixture setup 阶段挂起（exit 124）
- **环境/前提**：PG 套件，`clean_tables` autouse
- **复现**：连续跑 `tests/test_admin_api_permissions.py` 与后续任意 PG 测试（修复前）
- **期望 vs 实际**：权限测试应 hermetic；实际曾打开真实 DuckDB→PG attach
- **边界**：测试 / duckdb_service 单例 / PG 连接
- **严重度**：P0；**复现性**：always
- **回归测试**：`pytest tests/test_admin_api_permissions.py`（7 passed @ 2026-09-27）
- **owner**：#22（修复 PR #29，`FakeAnalytics` 注入）

### D-2 收藏测试触发真实后台向量重建 — #27 ✅ 已修复关闭（2026-09-27）
- **症状**：收藏测试后、content pipeline 测试前 fixture 挂起 180s+
- **复现**：连续跑 `test_content_favorite_api.py` → `test_content_pipeline.py`（修复前）
- **期望 vs 实际**：API 测试不启动生产后台任务；实际 `trigger_vector_rebuild` 泄漏跨库事务
- **边界**：测试 / interest_vector_service / PG 事务
- **严重度**：P0；**复现性**：always
- **回归测试**：连续执行 `pytest tests/test_content_favorite_api.py tests/test_content_pipeline.py`（15 passed @ 2026-09-27）
- **owner**：#27（修复 PR #33 测试隔离 + PR #56 生产侧任务追踪/优雅关闭）

### D-3 分析恢复 / inflight 去重 / post-sync drain 回归簇 — #35 ✅ 已修复关闭（2026-09-27）
- **症状**：六项测试失败（权限契约过时 / 旧同步后处理函数引用 / DB 连接跨事件循环复用）
- **复现**：`pytest tests/test_analysis_recovery.py tests/test_analysis_jobs_persistence.py tests/test_analysis_notification_permissions.py`
- **期望 vs 实际**：六项应全绿；实际三种独立根因
- **边界**：测试契约 / analysis job 持久化 / 事件循环
- **严重度**：P0；**复现性**：always（修复前）
- **回归测试**：同上复现命令（47 passed @ 2026-09-27）
- **owner**：#35（修复 PR #38 / #43 / #47；组合验证 PR #48 已关闭未合并，由新鲜运行取代）

### D-4 DuckDB Today Picks 查询契约回归 — #45 ✅ 已修复关闭（2026-09-27）
- **症状**：四项 Today Picks 查询测试失败
- **根因**：测试 fixture 临时表缺 `content_type` 列（契约重构后未跟上），非生产 SQL 回归
- **复现**：`pytest tests/test_duckdb_service.py -k today_picks`
- **边界**：测试 fixture / DuckDB 查询契约
- **严重度**：P1；**复现性**：always（修复前）
- **回归测试**：同上（4 passed @ 2026-09-27）
- **owner**：#45（修复 PR #54）

### D-5 依赖安全漏洞 — #4 🔴 进行中
- **症状**：pip-audit / npm audit 报漏洞
- **环境**：uv.lock 锁定生产依赖（2026-09-27 重扫）
- **期望 vs 实际**：无未处置高危漏洞；实际后端 12 条公告（按**唯一公告 ID** 计，pip-audit 2.7.3 于 2026-09-27 复扫：cryptography 45.0.7 五条，全清零需 ≥50.0.0；starlette 0.46.2 七条，需 ≥1.3.1，涉及 fastapi 连带大版本升级。pip-audit 按 PYSEC/GHSA 别名拆行时原始输出为 8+14 行，口径不同数字会随 OSV 库日更漂移）+ 前端 6 条（3 moderate / 2 high / 1 critical，`fixAvailable` 均为 true，`npm audit fix` 可修）
- **边界**：依赖 / 部署镜像 / CI security-scan 作业
- **严重度**：P0；**复现性**：always
- **回归测试**：CI `security-scan` 作业（`workflow_dispatch` 可手动触发）
- **owner**：#4（最新扫描结果与修复路径见 issue 评论）
- **日志/证据**：`uvx pip-audit -r <uv export --frozen 产物> --no-deps --disable-pip`

### D-6 OAuth 回调经 URL fragment 传完整凭证 — #63 🟡 待实现（P2）
- 非缺陷而是安全收窄项：HttpOnly cookie 已下发，但 fragment 仍暴露 token 给前端 JS。
- 回归测试候选：`tests_oauth_patch/`（断言 fragment 不含 token 后转正到该套件）。owner：#63。

### D-7 管理员第三方账号手动绑定流程缺失 — #64 🟡 待实现（P2）
- PR #62 已禁止向管理员自动关联，service 层 docstring 明确要求显式绑定流程但未实现。
- 回归测试候选：绑定端点四场景（正常 / 未 step-up / 绑定冲突 / 未验证邮箱）。owner：#64。

## 三、关键流程基线（9 项）

状态标记：✅ = 2026-09-27 在 main @ 7203847 新鲜复跑通过；📋 = 现有套件覆盖、未逐项复跑（跑全量即覆盖）。

| # | 关键流程 | 验证命令（backend/ 下，遵守§一） | 状态 |
|---|---|---|---|
| 1 | 登录 / 会话 / OAuth | `pytest tests/test_auth.py tests/test_oauth_service.py`；隔离版 `python -m pytest tests_oauth_patch/`（须 `python -m`，见 §一） | ✅（隔离套件 27/27（oauth_fix 8 + account_link_security 19）；auth + oauth_service 19 passed） |
| 2 | 信源创建 → 同步 → 内容落库 | `pytest tests/test_source_api.py tests/test_source_seed.py tests/test_api_source_scraper.py tests/test_content_pipeline.py` | 📋 |
| 3 | 抽取 / 富化 / 分类 | `pytest tests/test_enricher.py tests/test_classifier_contract.py tests/test_content_labeling.py tests/test_content_summary.py tests/test_recognizer.py tests/test_tag_normalization.py` | 📋 |
| 4 | 分析任务入队 → 恢复 → 完成/失败 | `pytest tests/test_analysis_recovery.py tests/test_analysis_jobs_persistence.py tests/test_job_tracker.py tests/test_analyses_api.py` | ✅（47 passed） |
| 5 | Today Picks 查询 / 标记 / 反馈 | `pytest tests/test_duckdb_service.py -k today_picks` + `pytest tests/test_today_picks.py tests/test_feedback_signal.py`（`-k` 是全局过滤器，不能与其它文件混在同一条命令，否则 feedback 用例被静默过滤） | ✅（today_picks 4/4；today_picks + feedback 25 passed） |
| 6 | 热榜同步 / 快照 | `pytest tests/test_trending_pipeline.py tests/test_trends_api.py tests/test_trend.py` | 📋 |
| 7 | DuckDB 不可用 → OLTP 回退 | `pytest tests/test_duckdb_service.py tests/test_latest_analysis_queries.py tests/test_digest_fallback.py tests/test_db_backend.py` | 📋 |
| 8 | 启动迁移 → 调度器 → 优雅停机 | `pytest tests/test_migrations.py tests/test_lifespan_duckdb_init.py tests/test_cache_warmup.py tests/test_startup_warmup_policy.py tests/test_interest_vector_lifecycle.py` | 📋（#6 将补充生命周期组合场景） |
| 9 | 前端主界面状态 | `cd frontend && npx tsc --noEmit && npm run test:coverage` | 📋 |

**全量基线**：`make test-backend`（一次性 PG 容器）+ 前端命令。截至 2026-09-27 未跑全量（本轮仅做针对性取证）；上一次全量 PG 套件运行记录见 #34 诊断 PR 时代，全量转绿是 #2 DoD 的剩余项。

## 四、维护规则

1. 新确认缺陷：先在此登记（十个维度），再开 issue；关闭 issue 时同步本表状态。
2. 关键流程新增/重构：同步更新§三的命令列。
3. 每次稳定化迭代（如 #2）收尾时，把「📋 未复跑」条目刷成当次结果。
