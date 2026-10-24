# Agent Guidelines

## 一、仓库与稳定入口

TopicEye 是内容创作者的选题雷达。agent 接口见 [AGENT_API.md](AGENT_API.md)。

- Postgres 保存事务数据；DuckDB 用于分析聚合。跨层读写前确认事实源，不能以聚合结果代替事务归属或版本判断。
- 事件事实与展示代表分开；只折叠可见且已接受的关系，不用相似关联隐藏文章，不覆盖人工关系。
- 入口层薄、业务编排在 service、ORM 查询在 repository；后端分层见第二节。
- 缺陷与交付状态看 GitHub，决策理由看 [`.agents/notes/`](.agents/notes/)，原始运行证据留本地 `.vidt/`。

修改相关功能前按需读取其长期合同；具体参数、算法、协议版本和运维步骤由这些文档维护：

| 范围 | 入口 |
|---|---|
| 事件归并、分页与生产启用门槛 | [docs/content-event-coverage.md](docs/content-event-coverage.md) |
| MCP OAuth 与 client 清理运维 | [docs/mcp-oauth-operations.md](docs/mcp-oauth-operations.md) |
| SelectBench 手动抽样、校准与导入 | [docs/selectbench.md](docs/selectbench.md) |
| 依赖审计口径与例外复核 | [docs/dependency-audit.md](docs/dependency-audit.md) |

本文只写仓库特有的事实与约束，与通用 skill 规则冲突时以本文为准。

## 二、动手前：权限与不可违背的约定

每个 agent 会话开场即生效的**三句权限档位**（任何一条要突破都必须先获所有者批准）：

1. **可写范围**：仅本仓库工作区（分支、暂存、本地提交）；仓库外文件一律只读。
2. **提交与远端写入**：`git commit`、push 分支、创建 PR 属常规动作；**合并 PR、直推 main、force-push、删除提交/历史改写——逐次审批**（见 4.1）。
3. **高风险操作**：数据库迁移、删除类命令、依赖大版本升级——先备份、留回滚路径，再动手（见 2.3）。

### 2.1 安全不变量

- **教训必须机器化**：事故/缺陷只有落成回归测试或 CI 门禁才算关闭，notes 记录理由，不能代替修复和验证。
- **中断重试纪律**：被中断的副作用操作不得盲目重试；先核实外部状态。只有只读或幂等操作可直接重试。
- **安全关键依赖**：加密、认证协议、沙箱等依赖必须有被证明的采用度与维护活跃度；其余位置也优先使用成熟依赖。
- **禁止安静失败**：启动组件等待、未挂载或跳过必须显式报错或 warning，静默 PENDING 按缺陷处理。

### 2.2 后端分层

依赖方向：入口 → services → repositories → models → sqlalchemy。

| 层 | 允许 | 禁止 |
|---|---|---|
| `api/v1/` | 路由、校验、调用 service/repository、响应整形 | ORM 模型导入、直接构造 SQL 或执行 session CRUD |
| `services/` | 业务编排、事务边界、跨 repository 组合 | 不得把业务编排反向放入 repository |
| `repositories/` | ORM 查询与 CRUD；继承 BaseRepository 或使用独立类 | 互相依赖、导入 services、承载业务编排 |
| `models/` | ORM 声明、字段、表约束 | 业务方法、副作用、IO |
| `schemas/` | Pydantic 请求/响应与序列化 | ORM 导入、DB 访问 |

API 层可使用 Enum 值对象、AsyncSession 类型注解、get_db 依赖注入与 IntegrityError 等异常类。
跨层共享的纯常量放 core。`app/mcp/` 与 API 同属入口层，遵守同样纪律。
`make layering` 的机器覆盖范围以 `backend/scripts/check_layering.py` 为准；豁免不得新增，机器检查不能代替表中其余边界的人工复核。

### 2.3 迁移与高风险变更

- **前置备份**：`cd backend && ./scripts/backup_db.sh`（PG pg_dump，默认保留 7 份）。
- **回滚**：`cd backend && ./scripts/rollback_migration.sh [target]`。先自动备份，再执行 downgrade；target 默认 `-1`，也可指定 revision 或 `base`。
- **验证**：先在测试环境执行 downgrade，确认上一版 schema 恢复且应用能启动，再执行已获批准的生产操作。
- 备份、回滚验证与执行权限各自成立；本地测试或代码合并不等于生产操作授权。

## 三、怎么验

### 3.1 数据库测试安全

`backend/tests/conftest.py` 的 autouse fixture 会对 DATABASE_URL 指向的库执行 TRUNCATE CASCADE 并终止其它连接。
**不得直接对开发库或生产库跑 pytest；即使是纯函数测试，也必须避开外层 fixture 的破坏性副作用。**

| 场景 | 命令与边界 |
|---|---|
| 后端全量 | `make test-backend`：自动创建一次性 PG，结束后清理；TEST_PG_PORT 可换端口 |
| 后端针对性 | `bash backend/scripts/test_full_local.sh <pytest参数>`，或明确指定自建一次性库 |
| OAuth 全 mock 目录 | `cd backend` 后执行 `DATABASE_URL='postgresql+asyncpg://dummy:dummy@localhost:5432/never_connect' uv run --no-sync python -m pytest tests_oauth_patch/`；必须使用 python -m |

pytest 的 `-k` 对本次指定的所有文件生效，不只作用于紧邻的文件。依赖事实源为 pyproject.toml + uv.lock，由 uv 管理。

### 3.2 按改动选择验证

先查同路径历史相关测试：`git log --name-only -5 -- <改动的文件>`。挑测时注意 PG/DuckDB 分工。
文档调整验证内容、引用和契约；代码调整跑相关行为回归。仅在变更、失败或未解决风险需要时扩大验证。

| 检查 | 命令 |
|---|---|
| Python 语法 | `cd backend && uv run python -m py_compile <changed-python-files>` |
| Shell 语法 | `bash -n <script>` |
| 分层 | `make layering` |
| 评分镜像 | `cd backend && uv run python scripts/check_scoring_mirror.py` |
| 刊物命名口径 | `cd backend && uv run python scripts/check_edition_naming.py` |
| AGENTS 引用 | `cd backend && uv run python scripts/check_agent_docs.py` |
| 前端类型 | `cd frontend && npx tsc --noEmit` |
| 前端测试及覆盖率 | `cd frontend && npm run test:coverage` |
| 完整静态质量门 | `make lint`；它不替代行为测试或真实环境验收 |

## 四、怎么交

正常路径：**有意义的变更必须有 issue → 分支 → PR → 检查绿 → 合并**，直推 main 不是常规路径。

### 4.1 审批闸门（所有者定）

逐次审批的那一类（第二节第 2 条），一次授权不覆盖下一次。其余属常规动作，默认行为是
实现并本地验证 → 报告变更摘要/diff → 等批准再 commit。**所有者也可在任务开始时一次性授权
本次范围内自行 commit 与建 PR**，agent 据此连做多个切片（每个切片仍是独立 commit，见 4.3），
结束时报告完整 diff，形状不合意 `git reset` 回退即可。

- **分支命名**：`issue-<number>-<short-slug>`（如 `issue-90-llm-fallback-requeue`）。
- **热修例外**：生产事故可直推 main 修复，但须在 24h 内补 PR 或在关联 issue 留 post-hoc 审计评论（原因、影响面、回归验证）。
- main 的 push CI 自动复验由 PR #65 引入；DoD 证据以 main 运行为准。

### 4.2 提交信息

形如 `<type>(<scope>): <中文说明>`，`type` 用 `fix` / `feat` / `chore` / `test` / `docs`，
`<scope>` 用这次实际碰到的模块名（`auth`、`scoring`、`trending` 等），不套固定清单。

```text
fix(auth): 降低登录链路数据库写锁等待
fix(trending): 合并重复信源筛选项
test(scoring): 补推荐档位边界的断言
docs: 跑测前必读补上 OAuth 隔离测试为什么必须 python -m
```

**说明用日常中文**，不搞翻译腔、不生造术语、不为强调堆砌修饰。读者应能从一句话
看出仓库变成了什么样，而不是读到「登记 X」「同步 Y」这类流程动作。

末尾的 `(#NN)` **只写 issue 号**——GitHub 两者共用编号空间，写错不报错，只让读的人分不清
是哪种对象；分支与 issue 的对应关系写在 PR 描述里。编号不是必写，只有它确实是这次改动的
原因时才写，且不追溯既往提交。

### 4.3 commit 边界

- 一个 commit 只做一件事：不要把 backend / frontend / docs / config 混在一起（除非
  同一修复必需），测试与它验证的代码同 commit。
- 本地文件不进库：`backend/.env`、数据库、venv、缓存、截图、生成的浏览器产物。
- 显式暂存路径，工作区有他人改动时禁 `git add -A`。

改写历史前建备份分支（`git branch backup/<理由>-<日期> HEAD`），改完用
`git diff <备份分支>..HEAD` 验证文件树未变——空 diff 说明只改了历史没改内容。本仓库**一律
禁止 force-push main**（不只是需审批）；其他分支的 force-push 按第二节第 2 条逐次过闸，
历史改写只存在于本地。

> 暂存范围、提交形状、产物边界由 skill 的 `git_workflow_guardrail.py`（G0–G4 阶段）
> 机器校验，本节只管机器判不了的「这算不算一件事」。

### 4.4 Verifier 契约

CI 作业以 [`.github/workflows/ci.yml`](.github/workflows/ci.yml) 为准，工作流检查全绿是合并前提；预存红必须显式处置并留记录。
PR 的 Verification 段记录本地命令、结果与覆盖范围；承载行为变更的 PR 还需独立复核结论，复核者不得是同一实现过程。
合并后核对 main push CI 与关联 issue 状态，不凭 PR merged 推断 issue 已关闭。

依赖扫描遵守 [审计口径](docs/dependency-audit.md)，不得为通过检查而降低安全门槛。
本地测试、CI、浏览器、真实 Provider 和生产证据分开记录，不能相互替代。

## 五、文档与决策如何收尾

`AGENTS.md` 是低频变化的协作契约：只放权限、安全、架构边界、验证入口和交付约定。
每个 PR 核对是否影响这些约定；仅约定本身、稳定入口或原文准确性发生变化时修改。普通实现变更默认不改本文件。

功能行为与运维参数放对应 docs；任务状态放 GitHub；决策理由放 notes；机器输出、截图和本轮证据放本地 `.vidt/`，不得随代码提交。

收尾明确给出一种 notes 处理结果：新建笔记、更新已有 owning note、或“无长期结论”及简短理由。
范围裁剪、否决方案、接受残余风险、验证不足与其它长期取舍按 [notes 约定](.agents/notes/README.md) 记录；机械改动不必逐次造笔记。
已有权威设计文档时使用薄指针，不复制另一份规则；notes 不承载当前 ship/hold 或 issue 状态真源。
涉及 notes 时按启用 skill 的 agent-notes 契约校验目录、Status 和链接；不要把历史叙述中的旧路径当当前命令逐项追着改。
