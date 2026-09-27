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

### D-5 依赖安全漏洞 — #4 ✅ 已修复关闭（2026-09-27）
- **症状**：pip-audit / npm audit 报漏洞
- **环境**：uv.lock 锁定生产依赖 + 前端 package-lock（2026-09-27 修复后复扫）
- **期望 vs 实际**：无未处置高危漏洞；修复后前后端均 0 公告（后端 `No known vulnerabilities found`，前端 `found 0 vulnerabilities`）
- **边界**：依赖 / 部署镜像 / CI security-scan 作业
- **严重度**：P0；**复现性**：always
- **回归测试**：CI `security-scan` 作业自 PR #68 起全绿；main push 自动复验由 #65 引入
- **owner**：#4（前端 #66：`npm audit fix` + vitest 5.0.2 + @types/node 22；后端 #67：cryptography 50.0.1；#68：fastapi 0.141.1 + starlette 1.7.0）
- **日志/证据**：`uvx pip-audit -r <uv export --frozen 产物> --no-deps --disable-pip`；修复前口径（后端 12 条唯一公告 + 前端 6 条）见 #4 评论存档

### D-6 OAuth 回调经 URL fragment 传完整凭证 — #63 ✅ 已修复关闭（2026-09-27）
- 安全收窄项：fragment 不再含 access token，仅带 provider/expires_at；凭证只经 HttpOnly cookie；前端回调页不消费任何凭证参数（旧 #token= 链接落地但不消费）。
- 回归测试：`tests_oauth_patch/test_oauth_fix.py` GitHub/Google 双 mock 断言 fragment 无 token。owner：#63（修复 PR #80；真实 provider E2E 待人工回归）。

### D-7 管理员第三方账号手动绑定流程缺失 — #64 ✅ 已修复关闭（2026-09-27）
- 已实现 step-up 绑定流程：`POST /auth/oauth/{provider}/bind/start`（重输密码→绑定意图入 session，TTL 10min）+ 回调绑定分支（会话本人校验、未验证邮箱拒绝、双冲突防护）；绑定成功不建新登录会话。
- 回归测试：`tests_oauth_patch/test_oauth_bind.py` 六场景（含会话不匹配与无意图回退）。owner：#64（修复 PR #81；设置页 UI 与解绑端点为后续）。

### D-8 /health/ready 判定门恒真 — #71 ✅ 已修复关闭（2026-09-27）
- 症状：ready 的 oltp 判定读自纯元数据 dict（`database_diagnostics` 不做连通性探测），恒为 True，`not_ready` 分支不可达；OLTP 不可达仍返回 ready。
- 边界：health 路由 / 部署路由层；复现性 always。
- 回归测试：`tests/test_health_endpoints.py` 四态路由级（正常 / 调度器禁用 / DuckDB 降级 / OLTP 不可达 503 + /health 别名）。owner：#71（Parent #6，修复 PR #75）。

### D-9 三处无主 create_task — #72 ✅ 已修复关闭（2026-09-27）
- 症状：`scheduler.py:1204/1205` 启动 rescan/恢复任务与 `daily_reports.py:294` 日报后台——无引用、无异常收集、不受停机管理；日报 `mark_error` 失败被裸 `except: pass` 吞掉可永卡 GENERATING。
- 边界：scheduler 启动路径 / daily_reports / lifespan 停机序。
- 回归测试：`tests/test_task_registry.py`（异常记日志注销 / drain 取消清空 / 超时告警不抛出）。owner：#72（Parent #6，修复 PR #76：`app/core/task_registry.py` 收编三处 + mark_error 留痕）。

### D-10 优雅停机链中断点 — #73 ✅ 已修复关闭（2026-09-27）
- 症状：`_cache_warmup_task` 非 CancelledError 异常会中断后续全部清理步骤；jieba 预热 await 无超时且 `to_thread` 不可取消，可挂死停机；整体停机无 deadline。
- 回归测试：`tests/test_shutdown_prewarm.py`（异常不外抛且留痕 / jieba 超时不挂死 / 正常与已取消路径）。owner：#73（Parent #6，修复 PR #77：`_shutdown_prewarm_tasks`）。

## 三、关键流程基线（9 项）

状态标记：✅ = 2026-09-27 在 main @ 7203847 新鲜复跑通过；📋 = 现有套件覆盖、未逐项复跑（跑全量即覆盖）。

| # | 关键流程 | 验证命令（backend/ 下，遵守§一） | 状态 |
|---|---|---|---|
| 1 | 登录 / 会话 / OAuth | `pytest tests/test_auth.py tests/test_oauth_service.py`；隔离版 `python -m pytest tests_oauth_patch/`（须 `python -m`，见 §一） | ✅（隔离套件 27/27（oauth_fix 8 + account_link_security 19）；auth + oauth_service 19 passed） |
| 2 | 信源创建 → 同步 → 内容落库 | `pytest tests/test_source_api.py tests/test_source_seed.py tests/test_api_source_scraper.py tests/test_content_pipeline.py` | ✅（2026-09-27 全量 exit 0，#68 后） |
| 3 | 抽取 / 富化 / 分类 | `pytest tests/test_enricher.py tests/test_classifier_contract.py tests/test_content_labeling.py tests/test_content_summary.py tests/test_recognizer.py tests/test_tag_normalization.py` | ✅（同上） |
| 4 | 分析任务入队 → 恢复 → 完成/失败 | `pytest tests/test_analysis_recovery.py tests/test_analysis_jobs_persistence.py tests/test_job_tracker.py tests/test_analyses_api.py` | ✅（47 passed） |
| 5 | Today Picks 查询 / 标记 / 反馈 | `pytest tests/test_duckdb_service.py -k today_picks` + `pytest tests/test_today_picks.py tests/test_feedback_signal.py`（`-k` 是全局过滤器，不能与其它文件混在同一条命令，否则 feedback 用例被静默过滤） | ✅（today_picks 4/4；today_picks + feedback 25 passed） |
| 6 | 热榜同步 / 快照 | `pytest tests/test_trending_pipeline.py tests/test_trends_api.py tests/test_trend.py` | ✅（2026-09-27 全量 exit 0，#68 后） |
| 7 | DuckDB 不可用 → OLTP 回退 | `pytest tests/test_duckdb_service.py tests/test_latest_analysis_queries.py tests/test_digest_fallback.py tests/test_db_backend.py` | ✅（同上） |
| 8 | 启动迁移 → 调度器 → 优雅停机 | `pytest tests/test_migrations.py tests/test_lifespan_duckdb_init.py tests/test_cache_warmup.py tests/test_startup_warmup_policy.py tests/test_interest_vector_lifecycle.py tests/test_task_registry.py tests/test_shutdown_prewarm.py tests/test_rescan_selfheal.py tests/test_health_endpoints.py` | ✅（2026-09-27 全量 exit 0 ×2；#6 生命周期补充已并入，PR #74~#78） |
| 9 | 前端主界面状态 | `cd frontend && npx tsc --noEmit && npm run test:coverage` | ✅（2026-09-27 tsc 通过 + 147/147 + coverage 通过，#66 vitest 5） |

**全量基线**：`make test-backend`（一次性 PG 容器）+ 前端命令。2026-09-27 全量转绿：#67（cryptography 50.0.1）与 #68（fastapi 0.141.1 / starlette 1.7.0）各跑一次全量均 exit 0；main push CI（#65 引入）@ `9da010e` 起全绿，#2 的全量转绿 DoD 达成。同日 #6 生命周期加固波（PR #74~#78）最终状态全量 exit 0（含新增 5 个生命周期测试文件；#77 所引的中间态全量日志被截断无结论行，以本最终状态运行覆盖实证）。

## 四、维护规则

1. 新确认缺陷：先在此登记（十个维度），再开 issue；关闭 issue 时同步本表状态。
2. 关键流程新增/重构：同步更新§三的命令列。
3. 每次稳定化迭代（如 #2）收尾时，把「📋 未复跑」条目刷成当次结果。
